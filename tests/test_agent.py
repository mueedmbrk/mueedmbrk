"""Tests for scheduling rules, intent parsing and call orchestration."""

import json
from datetime import date, datetime, timedelta

import pytest

from src.agent import BookingIntent, describe_alternatives, parse_intent
from src.config import Settings
from src.integrations import InMemoryCalendar, NullNotifier
from src.orchestrator import AppointmentAgent
from src.scheduling import BookingRules, BookingStatus, Scheduler, Slot

MONDAY = datetime(2026, 3, 2, 8, 0)          # a Monday, before opening
SATURDAY = datetime(2026, 3, 7, 10, 0)


def slot_at(day: datetime, hour: int, minute: int = 0, minutes: int = 30) -> Slot:
    start = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return Slot(start, start + timedelta(minutes=minutes))


@pytest.fixture
def rules() -> BookingRules:
    return BookingRules(opening_hour=9, closing_hour=17, slot_minutes=30)


@pytest.fixture
def scheduler(rules) -> Scheduler:
    return Scheduler(rules)


# ------------------------------------------------------------------ slot maths

def test_overlap_uses_half_open_intervals():
    """10:00-10:30 and 10:30-11:00 are back-to-back, not a clash."""
    first = slot_at(MONDAY, 10)
    second = slot_at(MONDAY, 10, 30)
    assert first.overlaps(second) is False


def test_genuine_overlap_is_detected():
    assert slot_at(MONDAY, 10).overlaps(slot_at(MONDAY, 10, 15)) is True


def test_buffer_creates_a_clash_between_adjacent_slots():
    scheduler = Scheduler(BookingRules(buffer_minutes=15))
    booked = [slot_at(MONDAY, 10, 30)]
    assert scheduler.is_free(slot_at(MONDAY, 10), booked) is False


def test_slots_sort_by_start_time():
    later, earlier = slot_at(MONDAY, 14), slot_at(MONDAY, 9)
    assert sorted([later, earlier])[0] == earlier


# ------------------------------------------------------------- rules and hours

def test_day_slots_span_opening_hours(rules):
    slots = rules.day_slots(date(2026, 3, 2))
    assert len(slots) == 16                      # 9am-5pm in 30-minute slots
    assert slots[0].start.hour == 9
    assert slots[-1].end.hour == 17


def test_no_slots_on_a_non_working_day(rules):
    assert rules.day_slots(date(2026, 3, 7)) == []   # Saturday


def test_appointment_must_fit_entirely_inside_hours(rules):
    """A 30-minute slot starting at 16:45 would run past a 17:00 close."""
    assert rules.within_hours(slot_at(MONDAY, 16, 45)) is False
    assert rules.within_hours(slot_at(MONDAY, 16, 30)) is True


def test_rules_reject_an_inverted_day():
    with pytest.raises(ValueError):
        BookingRules(opening_hour=18, closing_hour=9)


# ---------------------------------------------------------------- booking flow

def test_free_slot_is_confirmed(scheduler):
    result = scheduler.book(slot_at(MONDAY, 10), busy=[], now=MONDAY)
    assert result.confirmed
    assert result.status is BookingStatus.CONFIRMED


def test_double_booking_is_refused(scheduler):
    booked = [slot_at(MONDAY, 10)]
    result = scheduler.book(slot_at(MONDAY, 10), booked, now=MONDAY)
    assert result.status is BookingStatus.SLOT_TAKEN


def test_weekend_request_is_refused(scheduler):
    result = scheduler.book(slot_at(SATURDAY, 10), busy=[], now=MONDAY)
    assert result.status is BookingStatus.NON_WORKING_DAY


def test_after_hours_request_is_refused(scheduler):
    result = scheduler.book(slot_at(MONDAY, 20), busy=[], now=MONDAY)
    assert result.status is BookingStatus.OUTSIDE_HOURS


def test_past_request_is_refused(scheduler):
    result = scheduler.book(slot_at(MONDAY, 10), busy=[], now=MONDAY.replace(hour=14))
    assert result.status is BookingStatus.IN_THE_PAST


def test_request_beyond_the_horizon_is_refused(scheduler):
    far = MONDAY + timedelta(days=90)
    result = scheduler.book(slot_at(far, 10), busy=[], now=MONDAY)
    assert result.status is BookingStatus.TOO_FAR_AHEAD


@pytest.mark.parametrize(
    "slot,now",
    [
        (slot_at(MONDAY, 10), MONDAY.replace(hour=14)),      # past
        (slot_at(SATURDAY, 10), MONDAY),                     # weekend
        (slot_at(MONDAY, 20), MONDAY),                       # after hours
    ],
)
def test_every_refusal_offers_alternatives(scheduler, slot, now):
    """A caller told only "no" hangs up; one offered options books."""
    result = scheduler.book(slot, busy=[], now=now)
    assert result.confirmed is False
    assert len(result.alternatives) > 0


def test_next_available_skips_busy_slots(scheduler):
    busy = [slot_at(MONDAY, 9), slot_at(MONDAY, 9, 30)]
    upcoming = scheduler.next_available(MONDAY, busy, count=1)
    assert upcoming[0].start.hour == 10


def test_next_available_rolls_over_the_weekend(scheduler):
    friday = datetime(2026, 3, 6, 16, 45)
    upcoming = scheduler.next_available(friday, busy=[], count=1)
    assert upcoming[0].start.date() == date(2026, 3, 9)   # the following Monday


# ------------------------------------------------------------- intent parsing

class FakeLLM:
    """Returns queued replies, so intent parsing is tested without the network."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, messages: list[dict]) -> str:
        self.calls.append((system, messages))
        return self.replies.pop(0) if self.replies else "Understood."


def intent_json(**overrides) -> str:
    payload = {
        "intent": "book",
        "datetime": "2026-03-02T10:00",
        "name": "Sara",
        "phone": "+923001234567",
        "reason": "consultation",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_intent_is_parsed_from_json():
    intent = parse_intent(FakeLLM(intent_json()), "I'd like Monday at ten", MONDAY)
    assert intent.intent == "book"
    assert intent.requested_datetime == datetime(2026, 3, 2, 10, 0)
    assert intent.name == "Sara"
    assert intent.is_actionable


def test_json_wrapped_in_prose_or_fences_is_recovered():
    wrapped = f"Here you go:\n```json\n{intent_json()}\n```\nHope that helps."
    intent = parse_intent(FakeLLM(wrapped), "Monday at ten", MONDAY)
    assert intent.requested_datetime == datetime(2026, 3, 2, 10, 0)


def test_unparseable_model_output_does_not_crash_the_call():
    intent = parse_intent(FakeLLM("I'm not sure what you mean"), "mumble", MONDAY)
    assert intent.intent == "unclear"
    assert intent.is_actionable is False


def test_low_confidence_is_not_actionable():
    """A confident wrong booking is worse than asking the caller to repeat themselves."""
    intent = parse_intent(FakeLLM(intent_json(confidence=0.3)), "sometime soon?", MONDAY)
    assert intent.confidence == 0.3
    assert intent.is_actionable is False


def test_missing_datetime_is_not_actionable():
    intent = parse_intent(FakeLLM(intent_json(datetime=None, confidence=0.0)), "hello?", MONDAY)
    assert intent.is_actionable is False


def test_invalid_datetime_string_is_ignored():
    intent = parse_intent(FakeLLM(intent_json(datetime="next tuesdayish")), "?", MONDAY)
    assert intent.requested_datetime is None


def test_empty_transcript_short_circuits():
    llm = FakeLLM(intent_json())
    intent = parse_intent(llm, "   ", MONDAY)
    assert intent.intent == "unclear"
    assert llm.calls == [], "an empty transcript must not cost a model call"


def test_confidence_is_clamped():
    intent = parse_intent(FakeLLM(intent_json(confidence=5.0)), "x", MONDAY)
    assert intent.confidence == 1.0


# ------------------------------------------------------------- orchestration

@pytest.fixture
def config() -> Settings:
    return Settings(
        api_key="test", opening_hour=9, closing_hour=17, slot_minutes=30,
        max_days_ahead=30, escalation_webhook_url="",
    )


def build_agent(llm, calendar=None, config=None) -> AppointmentAgent:
    return AppointmentAgent(
        llm=llm,
        calendar=calendar or InMemoryCalendar(),
        notifier=NullNotifier(),
        config=config,
        business_name="Test Clinic",
    )


def test_successful_booking_writes_the_event_and_texts_the_caller(config):
    calendar = InMemoryCalendar()
    notifier = NullNotifier()
    agent = AppointmentAgent(
        llm=FakeLLM(intent_json(), "You're booked for Monday at ten."),
        calendar=calendar,
        notifier=notifier,
        config=config,
        business_name="Test Clinic",
    )

    outcome = agent.handle_transcript("Monday at ten please", now=MONDAY)

    assert outcome.booked
    assert outcome.event_id is not None
    assert len(calendar.created) == 1
    assert outcome.sms_sent and len(notifier.sent) == 1


def test_taken_slot_offers_alternatives_instead_of_booking(config):
    calendar = InMemoryCalendar(busy=[slot_at(MONDAY, 10)])
    agent = build_agent(FakeLLM(intent_json(), "That's taken, how about ten thirty?"), calendar, config)

    outcome = agent.handle_transcript("Monday at ten", now=MONDAY)

    assert outcome.booked is False
    assert outcome.booking.status is BookingStatus.SLOT_TAKEN
    assert calendar.created == [], "nothing may be written when the slot is refused"


def test_unclear_request_asks_for_clarification(config):
    agent = build_agent(FakeLLM(intent_json(confidence=0.2), "When suits you?"), config=config)
    outcome = agent.handle_transcript("erm, sometime?", now=MONDAY)

    assert outcome.booked is False
    assert outcome.reply == "When suits you?"


def test_cancellation_goes_straight_to_a_human(config):
    agent = build_agent(FakeLLM(intent_json(intent="cancel")), config=config)
    outcome = agent.handle_transcript("I need to cancel", now=MONDAY)

    assert outcome.escalated is True
    assert outcome.booked is False


def test_calendar_failure_never_reports_a_false_confirmation(config):
    """If the write fails there is no appointment — saying otherwise is the worst outcome."""

    class BrokenCalendar(InMemoryCalendar):
        def create_event(self, slot, summary, description=""):
            raise RuntimeError("calendar unavailable")

    agent = build_agent(FakeLLM(intent_json()), BrokenCalendar(), config)
    outcome = agent.handle_transcript("Monday at ten", now=MONDAY)

    assert outcome.booked is False
    assert outcome.escalated is True


def test_outcome_serialises_for_a_webhook(config):
    agent = build_agent(FakeLLM(intent_json(), "Booked."), config=config)
    data = agent.handle_transcript("Monday at ten", now=MONDAY).as_dict()

    assert data["booked"] is True
    assert data["slot"]["start"].startswith("2026-03-02T10:00")
    assert json.dumps(data)   # must be JSON-serialisable end to end


# ------------------------------------------------------------------- phrasing

def test_alternatives_are_read_as_natural_speech():
    slots = [slot_at(MONDAY, 9), slot_at(MONDAY, 10), slot_at(MONDAY, 11)]
    spoken = describe_alternatives(slots)
    assert ", or " in spoken
    assert "T09" not in spoken, "spoken output must never contain ISO timestamps"


def test_no_availability_is_phrased_gracefully():
    assert "no availability" in describe_alternatives([])
