# videostream.py
# Handles a single video feed — capturing and providing frames.
# Supports local devices, RTSP, HTTP/HTTPS, HLS (.m3u8), RTMP, and DASH sources.
# Shows animated TV static while connecting, reconnecting, or dead.
# Exponential backoff retry — 20 attempts max, 1s base, 120s ceiling.

import cv2
import threading
import time
import numpy as np
from urllib.parse import urlparse, urlunparse

MAX_ATTEMPTS    = 20
BASE_DELAY      = 1.0     # seconds
MAX_DELAY       = 120.0   # seconds (2-minute ceiling)
MAX_READ_FAILS  = 5       # consecutive bad reads before triggering reconnect

STATIC_W = 640
STATIC_H = 360

_NETWORK_SCHEMES = ('http://', 'https://', 'rtsp://', 'rtmp://', 'rtmps://', 'rtp://')


class VideoStream:
    def __init__(self, source, credentials=None, log_cb=None):
        """
        source      — int (local device index), file path, or network URL.
        credentials — (username, password) tuple or None.
        log_cb      — callable(message, ok=True) routed to the console.
        """
        self.source = source
        self.cap    = None

        self._lock       = threading.Lock()
        self._cred_lock  = threading.Lock()
        self._frame      = None
        self._last_w     = STATIC_W
        self._last_h     = STATIC_H
        self._running    = False
        self._thread     = None
        self._status     = 'connecting'  # connecting | live | reconnecting | dead

        self._retry_event   = threading.Event()
        self._credentials   = credentials
        self._auth_cb       = None
        self._auth_prompted = False

        self._log_cb = log_cb or (lambda msg, ok=True: print(f"[VideoStream] {msg}"))

    # ─────────────────────────────────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def status(self):
        """One of: 'connecting', 'live', 'reconnecting', 'dead'."""
        return self._status

    @property
    def width(self):
        if self.cap and self.cap.isOpened():
            return int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        return self._last_w

    @property
    def height(self):
        if self.cap and self.cap.isOpened():
            return int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return self._last_h

    def set_auth_callback(self, cb):
        """Register a callback invoked (from capture thread) when auth is suspected."""
        self._auth_cb = cb

    def set_credentials(self, username, password):
        """Provide credentials for URL authentication. Thread-safe."""
        with self._cred_lock:
            self._credentials = (username, password)

    def interrupt_wait(self):
        """Wake up a sleeping retry delay immediately."""
        self._retry_event.set()

    def start(self):
        """Start the capture thread."""
        self._running = True
        self._status  = 'connecting'
        self._thread  = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Stop capturing and release resources."""
        self._running = False
        self._retry_event.set()   # unblock any sleeping retry
        if self._thread:
            self._thread.join(timeout=3)
        if self.cap:
            self.cap.release()
            self.cap = None

    def restart(self):
        """Stop and restart the capture from scratch (e.g. after providing credentials)."""
        self._running = False
        self._retry_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self.cap:
            self.cap.release()
            self.cap = None
        self._frame         = None
        self._status        = 'connecting'
        self._auth_prompted = False
        self._running       = True
        self._retry_event   = threading.Event()
        self._thread        = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def get_frame(self):
        """Return the latest live frame, or None if not yet available."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def get_static_frame(self):
        """
        Generate an animated TV-static frame with status label.
        Called by FeedManager when the stream is not live.
        Each call produces fresh noise for animation.
        """
        h, w = self._last_h, self._last_w

        # Random grayscale noise — fresh each call for animation
        noise = np.random.randint(0, 220, (h, w), dtype=np.uint8)
        frame = np.stack([noise, noise, noise], axis=-1)

        # Dim to a dark, authentic static appearance
        frame = (frame.astype(np.float32) * 0.14).astype(np.uint8)

        # CRT scan-line effect — every other row slightly darker
        frame[1::2] = (frame[1::2].astype(np.float32) * 0.55).astype(np.uint8)

        # Status label
        label_map = {
            'connecting':   'CONNECTING...',
            'reconnecting': 'RECONNECTING...',
            'dead':         'FEED LOST',
        }
        label = label_map.get(self._status, 'WAITING')

        cx = w // 2
        cy = h // 2

        # Drop shadow for legibility over noise
        cv2.putText(frame, label,
                    (cx - 115, cy - 8),
                    cv2.FONT_HERSHEY_COMPLEX, 0.55, (15, 15, 15), 3)
        cv2.putText(frame, label,
                    (cx - 115, cy - 8),
                    cv2.FONT_HERSHEY_COMPLEX, 0.55, (165, 165, 165), 1)

        # Source string — truncated to fit
        src = str(self.source)
        if len(src) > 58:
            src = '...' + src[-55:]
        cv2.putText(frame, src,
                    (cx - 170, cy + 20),
                    cv2.FONT_HERSHEY_COMPLEX_SMALL, 0.35, (75, 75, 75), 1)

        return frame

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _log(self, msg, ok=True):
        self._log_cb(msg, ok=ok)

    def _is_network_source(self):
        return (isinstance(self.source, str)
                and self.source.lower().startswith(_NETWORK_SCHEMES))

    def _has_url_credentials(self):
        """True if credentials are already present (inline or injected)."""
        if not self._is_network_source():
            return False
        with self._cred_lock:
            if self._credentials:
                return True
        return bool(urlparse(self.source).username)

    def _effective_url(self):
        """Return the source URL with credentials injected if available."""
        with self._cred_lock:
            creds = self._credentials

        if not creds or not self._is_network_source():
            return self.source

        user, passwd = creds
        parsed = urlparse(self.source)

        # Don't double-inject if URL already carries credentials
        if parsed.username:
            return self.source

        host = parsed.hostname or ''
        if parsed.port:
            host = f"{host}:{parsed.port}"
        netloc = f"{user}:{passwd}@{host}"
        return urlunparse(parsed._replace(netloc=netloc))

    def _open(self):
        """Attempt to open the capture source. Returns True on success."""
        if self._is_network_source():
            url = self._effective_url()
            # Use FFmpeg backend for all network sources.
            # Explicit 10-second open/read timeouts avoid the 30-second default hang.
            # FFmpeg handles HTTP, HTTPS, RTSP, HLS (.m3u8), RTMP, and DASH natively.
            cap = cv2.VideoCapture(
                url,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10_000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10_000,
                ]
            )
        else:
            # Integer device index or local file path
            cap = cv2.VideoCapture(self.source)

        if cap.isOpened():
            self.cap = cap
            return True
        cap.release()
        return False

    def _sleep_interruptible(self, delay):
        """Sleep up to delay seconds, waking early if interrupt_wait() is called."""
        self._retry_event.wait(timeout=delay)
        self._retry_event.clear()

    def _connect_with_backoff(self, phase='connect'):
        """
        Attempt to open the source with exponential backoff.
        Returns True if connected, False if all attempts exhausted or stopped.
        phase — 'connect' (initial) or 'reconnect' (after drop)
        """
        attempt = 0
        while self._running and attempt < MAX_ATTEMPTS:
            if self._open():
                return True

            attempt += 1
            delay = min(BASE_DELAY * (2 ** (attempt - 1)), MAX_DELAY)

            self._log(
                f"[Feed {self.source}] {phase.capitalize()} attempt "
                f"{attempt}/{MAX_ATTEMPTS} failed — retrying in {delay:.0f}s.",
                ok=False
            )

            # On first connection failure for a bare network URL, request auth.
            # The UI shows the dialog; credentials will be set before the next attempt.
            if (phase == 'connect'
                    and attempt == 1
                    and self._is_network_source()
                    and not self._has_url_credentials()
                    and not self._auth_prompted):
                self._auth_prompted = True
                if self._auth_cb:
                    self._auth_cb()

            self._sleep_interruptible(delay)

        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Capture loop
    # ─────────────────────────────────────────────────────────────────────────

    def _capture_loop(self):
        # ── Phase 1: initial connection ───────────────────────────────────────
        self._status = 'connecting'
        connected = self._connect_with_backoff(phase='connect')

        if not self._running:
            return

        if not connected:
            self._status = 'dead'
            self._log(
                f"[Feed {self.source}] Gave up after {MAX_ATTEMPTS} connection attempts.",
                ok=False
            )
            return

        self._status = 'live'
        self._log(f"[Feed {self.source}] Connected.")

        # ── Phase 2: read loop ────────────────────────────────────────────────
        read_failures = 0

        while self._running:
            ret, frame = self.cap.read()

            if not ret:
                read_failures += 1
                if read_failures < MAX_READ_FAILS:
                    continue

                # Too many consecutive bad reads — attempt reconnect
                self._log(
                    f"[Feed {self.source}] Feed lost "
                    f"({read_failures} bad reads). Reconnecting...",
                    ok=False
                )
                self._status = 'reconnecting'
                with self._lock:
                    self._frame = None   # Switch display to static immediately

                self.cap.release()
                self.cap = None

                reconnected = self._connect_with_backoff(phase='reconnect')

                if not self._running:
                    return

                if not reconnected:
                    self._status = 'dead'
                    self._log(
                        f"[Feed {self.source}] Permanently lost after "
                        f"{MAX_ATTEMPTS} reconnect attempts.",
                        ok=False
                    )
                    return

                self._status  = 'live'
                read_failures = 0
                self._log(f"[Feed {self.source}] Reconnected.")
                continue

            # Good frame received
            read_failures = 0
            h, w = frame.shape[:2]
            with self._lock:
                self._frame  = frame
                self._last_w = w
                self._last_h = h