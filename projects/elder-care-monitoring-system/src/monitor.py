"""The monitoring loop: camera -> posture tracking -> carer alert."""

from __future__ import annotations

import argparse
import logging
import sys

import cv2

from .alerts import AlertDispatcher, build_dispatcher
from .config import Settings, settings as default_settings
from .detector import FrameAnalyzer, PostureTracker

logger = logging.getLogger(__name__)

BOX_UPRIGHT = (0, 200, 0)
BOX_FALLEN = (0, 0, 255)


class ElderCareMonitor:
    """Wires the pieces together and runs until the stream ends or the user quits."""

    def __init__(self, config: Settings, dispatcher: AlertDispatcher | None = None) -> None:
        self.config = config
        self.analyzer = FrameAnalyzer(min_contour_area=config.min_contour_area)
        self.tracker = PostureTracker(
            aspect_ratio_threshold=config.fall_aspect_ratio,
            confirm_frames=config.fall_confirm_frames,
            drop_velocity_threshold=config.drop_velocity,
        )
        self.dispatcher = dispatcher or build_dispatcher(config)

    def process_frame(self, frame) -> tuple[object, object]:
        """Analyse one frame. Returns ``(bbox, fall_event)`` — either may be ``None``."""
        bbox = self.analyzer.largest_person_box(frame)
        event = self.tracker.update(bbox)
        if event is not None:
            logger.warning(event.summary())
            self.dispatcher.dispatch(event.summary())
        return bbox, event

    def run(self, show_window: bool = True) -> int:
        capture = cv2.VideoCapture(self.config.resolved_source())
        if not capture.isOpened():
            logger.error("Could not open video source %r", self.config.camera_source)
            return 1

        # Thresholds are normalised against frame height, so tell the tracker the real one.
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        self.tracker.frame_height = height
        logger.info("Monitoring started on source %r (%dpx tall)", self.config.camera_source, height)

        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    logger.info("Video source ended.")
                    break

                bbox, event = self.process_frame(frame)

                if show_window:
                    self._draw(frame, bbox, event)
                    cv2.imshow("Elder Care Monitor", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        finally:
            capture.release()
            if show_window:
                cv2.destroyAllWindows()
        return 0

    def _draw(self, frame, bbox, event) -> None:
        if bbox is None:
            return
        x, y, w, h = bbox
        colour = BOX_FALLEN if event or self.tracker.posture.value == "horizontal" else BOX_UPRIGHT
        cv2.rectangle(frame, (x, y), (x + w, y + h), colour, 2)
        cv2.putText(
            frame,
            self.tracker.posture.value.upper(),
            (x, max(y - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            colour,
            2,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Elder care fall-detection monitor")
    parser.add_argument("--source", help="Webcam index, video file or RTSP URL")
    parser.add_argument("--headless", action="store_true", help="Run without a preview window")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = default_settings
    if args.source:
        config = Settings(camera_source=args.source)

    return ElderCareMonitor(config).run(show_window=not args.headless)


if __name__ == "__main__":
    sys.exit(main())
