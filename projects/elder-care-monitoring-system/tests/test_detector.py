"""Tests for the posture tracker.

These exercise the decision logic through bounding-box sequences rather than
video, which is the whole point of keeping ``PostureTracker`` free of OpenCV.
"""

import pytest

from src.detector import FallEvent, Posture, PostureTracker

FRAME_HEIGHT = 480


def standing_box(y: int = 100) -> tuple[int, int, int, int]:
    """A person taller than they are wide."""
    return (200, y, 60, 200)


def fallen_box(y: int = 380) -> tuple[int, int, int, int]:
    """A person wider than they are tall, low in the frame."""
    return (180, y, 200, 70)


@pytest.fixture
def tracker() -> PostureTracker:
    return PostureTracker(
        aspect_ratio_threshold=1.25,
        confirm_frames=10,
        drop_velocity_threshold=0.045,
        frame_height=FRAME_HEIGHT,
    )


def test_standing_never_alerts(tracker: PostureTracker) -> None:
    for _ in range(100):
        assert tracker.update(standing_box()) is None
    assert tracker.posture is Posture.UPRIGHT


def test_confirmed_fall_emits_event(tracker: PostureTracker) -> None:
    tracker.update(standing_box())

    events = [tracker.update(fallen_box()) for _ in range(20)]
    fired = [e for e in events if e is not None]

    assert len(fired) == 1, "a single fall must not alert more than once"
    assert isinstance(fired[0], FallEvent)
    assert fired[0].aspect_ratio > 1.25


def test_brief_bend_does_not_alert(tracker: PostureTracker) -> None:
    """Bending to pick something up goes horizontal briefly — that is not a fall."""
    tracker.update(standing_box())
    # Well under confirm_frames, and no sharp drop to corroborate.
    for _ in range(4):
        assert tracker.update(fallen_box(y=200)) is None
    for _ in range(10):
        assert tracker.update(standing_box()) is None


def test_sharp_drop_confirms_faster(tracker: PostureTracker) -> None:
    """A fast downward move halves the confirmation window."""
    tracker.update(standing_box(y=60))

    fired = None
    for i in range(10):
        # Large first step produces a drop velocity above the threshold.
        event = tracker.update(fallen_box(y=400))
        if event and fired is None:
            fired = (i, event)

    assert fired is not None
    index, event = fired
    assert index < 10, "corroborated fall should confirm before the full window"
    assert event.drop_velocity > 0


def test_recovery_resets_and_allows_new_alert(tracker: PostureTracker) -> None:
    """Someone who gets back up and falls again must trigger a second alert."""
    for _ in range(15):
        tracker.update(fallen_box())
    for _ in range(5):
        tracker.update(standing_box())

    assert tracker.posture is Posture.UPRIGHT

    second = [tracker.update(fallen_box()) for _ in range(20)]
    assert any(e is not None for e in second)


def test_missing_subject_decays_streak(tracker: PostureTracker) -> None:
    """An empty frame decays the streak instead of wiping it."""
    for _ in range(5):
        tracker.update(fallen_box())
    tracker.update(None)
    tracker.update(None)

    # Streak decayed by two, so two extra horizontal frames are now needed.
    events = [tracker.update(fallen_box()) for _ in range(4)]
    assert all(e is None for e in events)


def test_absent_before_any_frame(tracker: PostureTracker) -> None:
    assert tracker.posture is Posture.ABSENT


def test_reset_clears_state(tracker: PostureTracker) -> None:
    for _ in range(15):
        tracker.update(fallen_box())
    tracker.reset()
    assert tracker.posture is Posture.ABSENT
