# videostream.py
# Handles a single video feed — capturing, mirroring, and providing frames.

import cv2
import threading


class VideoStream:
    def __init__(self, source=0):
        self.source = source
        self.cap = cv2.VideoCapture(source)

        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open video source {source}")

        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    @property
    def width(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    @property
    def height(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def start(self):
        """Start capturing frames in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Stop capturing and release the source."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self.cap.release()

    def get_frame(self):
        """Get the latest frame, or None if not yet available."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def _capture_loop(self):
        consecutive_failures = 0
        max_failures = 10

        while self._running:
            ret, frame = self.cap.read()
            if not ret:
                consecutive_failures += 1
                print(f"[VideoStream] Failed to read frame from {self.source} ({consecutive_failures}/{max_failures})")
                if consecutive_failures >= max_failures:
                    print(f"[VideoStream] Feed {self.source} unreachable, stopping.")
                    self._running = False
                    break
                continue

            consecutive_failures = 0
            frame = cv2.flip(frame, 1) if isinstance(self.source, int) else frame

            with self._lock:
                self._frame = frame