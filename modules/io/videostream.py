# videostream.py
# Handles a single video feed — capturing, mirroring, and providing frames.

import cv2
import threading
import time


class VideoStream:
    def __init__(self, source=0):
        self.source = source
        self.cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    @property
    def width(self):
        if self.cap and self.cap.isOpened():
            return int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        return 0

    @property
    def height(self):
        if self.cap and self.cap.isOpened():
            return int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return 0

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
        if self.cap:
            self.cap.release()

    def get_frame(self):
        """Get the latest frame, or None if not yet available."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def _is_rtsp(self):
        return isinstance(self.source, str) and self.source.lower().startswith("rtsp")

    def _open(self):
        """Try to open the capture source. Returns True on success."""
        if self._is_rtsp():
            # Pass FFmpeg options to cap RTSP socket timeout at 5s instead of the
            # default 30s, so failed reads resolve quickly rather than hanging.
            cap = cv2.VideoCapture(
                self.source,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5_000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5_000,
                ]
            )
        else:
            cap = cv2.VideoCapture(self.source)

        if cap.isOpened():
            self.cap = cap
            return True
        cap.release()
        return False

    def _capture_loop(self):
        # RTSP streams can drop mid-session; fail fast with fewer retries since
        # each read now resolves in seconds rather than 30s.
        retry_delay  = 2.0
        max_failures = 3 if self._is_rtsp() else 10
        consecutive_failures = 0

        # Keep trying to open the source until connected or stopped
        while self._running and not self._open():
            print(f"[VideoStream] Could not open {self.source}, retrying in {retry_delay}s...")
            time.sleep(retry_delay)

        if not self._running:
            return

        print(f"[VideoStream] Connected to {self.source}")

        while self._running:
            ret, frame = self.cap.read()
            if not ret:
                consecutive_failures += 1
                print(f"[VideoStream] Failed to read frame from {self.source} ({consecutive_failures}/{max_failures})")
                if consecutive_failures >= max_failures:
                    print(f"[VideoStream] Feed {self.source} lost, attempting reconnect...")
                    self.cap.release()
                    consecutive_failures = 0
                    while self._running and not self._open():
                        print(f"[VideoStream] Reconnecting to {self.source} in {retry_delay}s...")
                        time.sleep(retry_delay)
                    if not self._running:
                        return
                    print(f"[VideoStream] Reconnected to {self.source}")
                continue

            consecutive_failures = 0
            frame = cv2.flip(frame, 1) if isinstance(self.source, int) else frame

            with self._lock:
                self._frame = frame