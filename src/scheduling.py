"""Availability and booking rules.

This is the part of a booking agent that must never be wrong, so it is deliberately
pure: dates in, dates out, no calendar API, no model, no network. Double-booking is
the failure that loses a client, and it is prevented here by explicit overlap checks
rather than by hoping the calendar API rejects the write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum


class BookingStatus(str, Enum):
    CONFIRMED = "confirmed"
    SLOT_TAKEN = "slot_taken"
    OUTSIDE_HOURS = "outside_hours"
    NON_WORKING_DAY = "non_working_day"
    TOO_FAR_AHEAD = "too_far_ahead"
    IN_THE_PAST = "in_the_past"


@dataclass(frozen=True, order=True)
class Slot:
    """A bookable window. Comparison is by start time, so slots sort naturally."""

    start: datetime
    end: datetime

    def overlaps(self, other: "Slot") -> bool:
        """Half-open intervals: a 10:00-10:30 slot does not clash with 10:30-11:00."""
        return self.start < other.end and other.start < self.end

    def with_buffer(self, minutes: int) -> "Slot":
        delta = timedelta(minutes=minutes)
        return Slot(self.start - delta, self.end + delta)

    def humanise(self) -> str:
        return self.start.strftime("%A %d %B at %I:%M %p").replace(" 0", " ")

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class BookingResult:
    status: BookingStatus
    slot: Slot | None = None
    alternatives: list[Slot] = None  # type: ignore[assignment]
    message: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status is BookingStatus.CONFIRMED

    def __post_init__(self) -> None:
        if self.alternatives is None:
            object.__setattr__(self, "alternatives", [])


@dataclass
class BookingRules:
    """The business's opening hours and slot policy."""

    opening_hour: int = 9
    closing_hour: int = 17
    slot_minutes: int = 30
    buffer_minutes: int = 0
    max_days_ahead: int = 30
    working_days: frozenset[int] = frozenset({0, 1, 2, 3, 4})

    def __post_init__(self) -> None:
        if self.opening_hour >= self.closing_hour:
            raise ValueError("opening_hour must be before closing_hour")
        if self.slot_minutes < 1:
            raise ValueError("slot_minutes must be positive")

    def is_working_day(self, day: date) -> bool:
        return day.weekday() in self.working_days

    def within_hours(self, slot: Slot) -> bool:
        """The whole appointment must fit inside opening hours, not just its start.

        Checking only the start time is the classic bug here: a 30-minute slot
        starting at 16:45 would be accepted and then run past a 17:00 close.
        """
        opening = datetime.combine(slot.start.date(), time(self.opening_hour), slot.start.tzinfo)
        closing = datetime.combine(slot.start.date(), time(self.closing_hour), slot.start.tzinfo)
        return slot.start >= opening and slot.end <= closing

    def day_slots(self, day: date, tzinfo=None) -> list[Slot]:
        """Every slot the business offers on a given day, ignoring existing bookings."""
        if not self.is_working_day(day):
            return []

        slots: list[Slot] = []
        cursor = datetime.combine(day, time(self.opening_hour), tzinfo)
        closing = datetime.combine(day, time(self.closing_hour), tzinfo)
        duration = timedelta(minutes=self.slot_minutes)

        while cursor + duration <= closing:
            slots.append(Slot(cursor, cursor + duration))
            cursor += duration

        return slots


class Scheduler:
    """Answers "is this free?" and "what else is there?" against a set of bookings."""

    def __init__(self, rules: BookingRules | None = None) -> None:
        self.rules = rules or BookingRules()

    def is_free(self, slot: Slot, busy: list[Slot]) -> bool:
        """Free means no overlap with any existing booking, once buffers are applied."""
        padded = slot.with_buffer(self.rules.buffer_minutes)
        return not any(padded.overlaps(booking) for booking in busy)

    def available_slots(
        self, day: date, busy: list[Slot], tzinfo=None, limit: int | None = None
    ) -> list[Slot]:
        free = [s for s in self.rules.day_slots(day, tzinfo) if self.is_free(s, busy)]
        return free[:limit] if limit else free

    def next_available(
        self,
        after: datetime,
        busy: list[Slot],
        count: int = 3,
        search_days: int | None = None,
    ) -> list[Slot]:
        """The next ``count`` free slots, scanning forward day by day."""
        search_days = search_days or self.rules.max_days_ahead
        found: list[Slot] = []

        for offset in range(search_days + 1):
            day = (after + timedelta(days=offset)).date()
            for slot in self.available_slots(day, busy, tzinfo=after.tzinfo):
                if slot.start > after:
                    found.append(slot)
                    if len(found) >= count:
                        return found

        return found

    def book(self, requested: Slot, busy: list[Slot], now: datetime) -> BookingResult:
        """Validate a requested slot against every rule, with alternatives on failure.

        A refusal always carries alternatives. A caller told only "that time does not
        work" hangs up; one offered two nearby options books an appointment.
        """
        alternatives = self.next_available(now, busy, count=3)

        if requested.start <= now:
            return BookingResult(
                BookingStatus.IN_THE_PAST,
                alternatives=alternatives,
                message="That time has already passed.",
            )

        if (requested.start.date() - now.date()).days > self.rules.max_days_ahead:
            return BookingResult(
                BookingStatus.TOO_FAR_AHEAD,
                alternatives=alternatives,
                message=f"We only book up to {self.rules.max_days_ahead} days ahead.",
            )

        if not self.rules.is_working_day(requested.start.date()):
            return BookingResult(
                BookingStatus.NON_WORKING_DAY,
                alternatives=alternatives,
                message="We are closed that day.",
            )

        if not self.rules.within_hours(requested):
            return BookingResult(
                BookingStatus.OUTSIDE_HOURS,
                alternatives=alternatives,
                message=(
                    f"That falls outside our hours of "
                    f"{self.rules.opening_hour}:00 to {self.rules.closing_hour}:00."
                ),
            )

        if not self.is_free(requested, busy):
            return BookingResult(
                BookingStatus.SLOT_TAKEN,
                alternatives=alternatives,
                message="That slot is already booked.",
            )

        return BookingResult(
            BookingStatus.CONFIRMED,
            slot=requested,
            message=f"Confirmed for {requested.humanise()}.",
        )
