"""Tests for alert fan-out and cooldown behaviour."""

from src.alerts import AlertChannel, AlertDispatcher


class RecordingChannel(AlertChannel):
    def __init__(self, succeed: bool = True) -> None:
        self.succeed = succeed
        self.messages: list[str] = []

    def send(self, message: str) -> bool:
        self.messages.append(message)
        return self.succeed


def test_dispatch_reaches_every_channel() -> None:
    a, b = RecordingChannel(), RecordingChannel()
    dispatcher = AlertDispatcher([a, b], cooldown_seconds=60)

    assert dispatcher.dispatch("fall", now=1000.0) is True
    assert a.messages == ["fall"] and b.messages == ["fall"]


def test_cooldown_suppresses_repeat_alerts() -> None:
    channel = RecordingChannel()
    dispatcher = AlertDispatcher([channel], cooldown_seconds=120)

    dispatcher.dispatch("first", now=1000.0)
    assert dispatcher.dispatch("second", now=1050.0) is False
    assert channel.messages == ["first"]

    assert dispatcher.dispatch("third", now=1200.0) is True
    assert channel.messages == ["first", "third"]


def test_one_failing_channel_does_not_block_the_others() -> None:
    broken, working = RecordingChannel(succeed=False), RecordingChannel()
    dispatcher = AlertDispatcher([broken, working])

    assert dispatcher.dispatch("fall", now=1.0) is True
    assert working.messages == ["fall"]


def test_all_channels_failing_reports_failure() -> None:
    dispatcher = AlertDispatcher([RecordingChannel(succeed=False)])
    assert dispatcher.dispatch("fall", now=1.0) is False
