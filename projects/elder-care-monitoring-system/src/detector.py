"""Fall detection.

The detection problem splits cleanly in two, and this module keeps the halves apart:

* ``PostureTracker`` is pure Python. Given the bounding box of the person in each
  frame it decides whether a fall has happened. No OpenCV, no camera — so the
  decision logic is unit-testable in milliseconds.
* ``FrameAnalyzer`` is the OpenCV half. It turns a raw frame into that bounding
  box via background subtraction and contour extraction.

Keeping them separate is what makes the thresholds tunable with confidence: you
can replay a box sequence through the tracker without touching a video file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

import cv2
import numpy as np

BoundingBox = tuple[int, int, int, int]  # x, y, w, h


class Posture(str, Enum):
    """What the silhouette currently looks like."""

    UPRIGHT = "upright"
    HORIZONTAL = "horizontal"
    ABSENT = "absent"


@dataclass
class FallEvent:
    """Everything a carer needs to triage the alert."""

    frame_index: int
    posture_frames: int
    aspect_ratio: float
    drop_velocity: float
    bbox: BoundingBox

    def summary(self) -> str:
        return (
            f"Fall detected at frame {self.frame_index}: subject horizontal for "
            f"{self.posture_frames} frames (aspect ratio {self.aspect_ratio:.2f}, "
            f"drop velocity {self.drop_velocity:.3f})"
        )


@dataclass
class PostureTracker:
    """Turns a stream of bounding boxes into confirmed fall events.

    Two independent signals have to agree before an alert fires:

    1. **Shape** — a standing person is taller than they are wide. When the box
       flips to wider-than-tall past ``aspect_ratio_threshold``, the posture is
       horizontal.
    2. **Persistence** — someone bending down to tie a shoelace also goes briefly
       horizontal, so the posture must hold for ``confirm_frames`` before it counts.

    A sharp downward move of the centroid (``drop_velocity_threshold``) is recorded
    as corroborating evidence and shortens the confirmation window, because a real
    fall arrives fast while sitting down on the floor does not.
    """

    aspect_ratio_threshold: float = 1.25
    confirm_frames: int = 18
    drop_velocity_threshold: float = 0.045
    frame_height: int = 480

    _horizontal_streak: int = field(default=0, init=False)
    _previous_centroid_y: Optional[float] = field(default=None, init=False)
    _peak_drop_velocity: float = field(default=0.0, init=False)
    _drop_corroborated: bool = field(default=False, init=False)
    _fall_active: bool = field(default=False, init=False)
    _frame_index: int = field(default=0, init=False)

    def reset(self) -> None:
        """Clear all state — call between separate video sources."""
        self._horizontal_streak = 0
        self._previous_centroid_y = None
        self._clear_episode()
        self._frame_index = 0

    def _clear_episode(self) -> None:
        """Forget the current fall episode once the subject is upright again."""
        self._peak_drop_velocity = 0.0
        self._drop_corroborated = False
        self._fall_active = False

    @property
    def posture(self) -> Posture:
        if self._previous_centroid_y is None:
            return Posture.ABSENT
        return Posture.HORIZONTAL if self._horizontal_streak else Posture.UPRIGHT

    def update(self, bbox: Optional[BoundingBox]) -> Optional[FallEvent]:
        """Feed one frame's bounding box; returns a ``FallEvent`` the moment a fall confirms.

        Passing ``None`` means nobody was found in the frame — the streak decays
        rather than resetting outright, so a person briefly occluded by furniture
        mid-fall does not erase the evidence collected so far.
        """
        self._frame_index += 1

        if bbox is None:
            self._horizontal_streak = max(0, self._horizontal_streak - 1)
            if self._horizontal_streak == 0:
                self._clear_episode()
            return None

        x, y, w, h = bbox
        aspect_ratio = w / max(h, 1)
        centroid_y = y + h / 2

        # Normalise the drop so the threshold is resolution-independent.
        drop_velocity = 0.0
        if self._previous_centroid_y is not None:
            drop_velocity = (centroid_y - self._previous_centroid_y) / max(self.frame_height, 1)
        self._previous_centroid_y = centroid_y

        if aspect_ratio < self.aspect_ratio_threshold:
            # Back upright — the subject recovered, so stand down any active alert.
            self._horizontal_streak = 0
            self._clear_episode()
            return None

        self._horizontal_streak += 1

        # The drop happens in a single frame, but confirmation lands many frames
        # later — so latch the evidence for the episode instead of reading the
        # instantaneous value, which has decayed to zero by the time we decide.
        if drop_velocity >= self.drop_velocity_threshold:
            self._drop_corroborated = True
        self._peak_drop_velocity = max(self._peak_drop_velocity, drop_velocity)

        # A fast drop is strong corroboration, so we need fewer confirming frames.
        required = self.confirm_frames
        if self._drop_corroborated:
            required = max(1, self.confirm_frames // 2)

        if self._horizontal_streak >= required and not self._fall_active:
            self._fall_active = True
            return FallEvent(
                frame_index=self._frame_index,
                posture_frames=self._horizontal_streak,
                aspect_ratio=aspect_ratio,
                drop_velocity=self._peak_drop_velocity,
                bbox=bbox,
            )
        return None


class FrameAnalyzer:
    """Extracts the subject's bounding box from a frame using background subtraction.

    MOG2 adapts to slow lighting changes (curtains, dusk) while still reacting to
    a person moving, which suits a room-monitoring camera that runs for days.
    Shadow pixels are labelled 127 by MOG2 and thresholded away here — untreated,
    a long shadow stretches the box sideways and fakes a horizontal posture.
    """

    def __init__(self, min_contour_area: int = 2500, history: int = 500) -> None:
        self.min_contour_area = min_contour_area
        self._subtractor = cv2.createBackgroundSubtractorMOG2(
            history=history, varThreshold=32, detectShadows=True
        )
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    def foreground_mask(self, frame: np.ndarray) -> np.ndarray:
        mask = self._subtractor.apply(frame)
        # Drop MOG2's shadow label (127); keep only confident foreground.
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel, iterations=2)
        mask = cv2.dilate(mask, self._kernel, iterations=2)
        return mask

    def largest_person_box(self, frame: np.ndarray) -> Optional[BoundingBox]:
        """Bounding box of the biggest moving blob, or ``None`` if the room is still."""
        mask = self.foreground_mask(frame)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return largest_box(contours, self.min_contour_area)


def largest_box(contours: Sequence[np.ndarray], min_area: int) -> Optional[BoundingBox]:
    """Pick the largest contour above ``min_area`` and return its bounding box."""
    candidates = [c for c in contours if cv2.contourArea(c) >= min_area]
    if not candidates:
        return None
    return cv2.boundingRect(max(candidates, key=cv2.contourArea))
