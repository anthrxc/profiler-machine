# modules/core/feed_manager.py
# Manages multiple video streams and their state.

import cv2
import threading
from modules.io.videostream import VideoStream
from modules.profiler.designation import Designator
from modules.profiler.alerts import AlertEngine
from modules.core.feeds_config import FeedsConfig


class FeedManager:
    def __init__(self, app, db, body_detector=None):
        self.app = app
        self.db = db
        self._feeds = {}
        self._lock = threading.Lock()
        self._focused = None
        self._designator = Designator(app, db, body_detector=body_detector)
        self._config = FeedsConfig()
        self._auth_request_cb = None  # Injected by MainWindow

        # AlertEngine is started after console is ready (set_console called)
        self._alert_engine = AlertEngine(
            db=db,
            designator=self._designator,
            console_cb=self._console_print,
            play_sound_cb=self._play_sound,
        )
        self._console_cb = None   # injected by MainWindow after construction

    def set_console(self, cb):
        """Called by MainWindow to inject the console print callback."""
        self._console_cb = cb
        self._alert_engine.start()

    def set_auth_request_cb(self, cb):
        """Called by MainWindow to receive feed-level auth-needed notifications."""
        self._auth_request_cb = cb

    def _console_print(self, text, ok=True):
        if self._console_cb:
            self._console_cb(text, ok=ok)

    def _play_sound(self, path):
        try:
            from modules.io.playsound import play_sound
            play_sound(path)
        except Exception as e:
            print(f"[FeedManager] Sound error: {e}")

    def _on_auth_needed(self, feed_id):
        """Called from VideoStream thread when authentication is suspected for a feed."""
        if self._auth_request_cb:
            self._auth_request_cb(feed_id)

    # -------------------------------------------------------------------------
    # Feed management
    # -------------------------------------------------------------------------

    def add_feed(self, source, flip_h=None, flip_v=None, credentials=None):
        """Add a new feed. Returns the feed_id assigned to it.

        flip_h / flip_v — pass True/False to force a value.
        If left as None, any existing saved config for this source is inherited;
        otherwise defaults to False.  This preserves flip flags across restarts
        without requiring the caller to re-supply them every time.
        """
        # Resolve flip flags: saved config wins over the default (False),
        # but an explicit True/False from the caller always takes priority.
        saved = self._config.find_by_source(source)
        resolved_h = flip_h if flip_h is not None else (saved.get('flip_h', False) if saved else False)
        resolved_v = flip_v if flip_v is not None else (saved.get('flip_v', False) if saved else False)

        with self._lock:
            feed_id = self._next_id()
            stream = VideoStream(
                source,
                credentials=credentials,
                log_cb=self._console_print,
            )
            stream.set_auth_callback(lambda fid=feed_id: self._on_auth_needed(fid))
            stream.start()
            self._feeds[feed_id] = stream
            print(f"[FeedManager] Added feed {feed_id}: {source} "
                  f"(flip_h={resolved_h}, flip_v={resolved_v})")
        self._config.add_feed(feed_id, source, flip_h=resolved_h, flip_v=resolved_v)
        return feed_id

    def provide_credentials(self, feed_id, username, password):
        """Supply credentials for a feed that required authentication.

        If the feed gave up (dead), it is restarted from scratch.
        Otherwise the retry delay is interrupted so it retries immediately.
        Returns True if the feed was found, False otherwise.
        """
        with self._lock:
            stream = self._feeds.get(feed_id)
        if not stream:
            return False
        stream.set_credentials(username, password)
        if stream.status == 'dead':
            stream.restart()
        else:
            stream.interrupt_wait()
        return True

    def remove_feed(self, feed_id):
        """Stop and remove a feed by ID."""
        with self._lock:
            if feed_id not in self._feeds:
                print(f"[FeedManager] Feed {feed_id} not found.")
                return
            self._feeds[feed_id].stop()
            del self._feeds[feed_id]
            if self._focused == feed_id:
                self._focused = None
            print(f"[FeedManager] Removed feed {feed_id}.")
        self._config.remove_feed(feed_id)

    def focus_feed(self, feed_id):
        """Zoom into a specific feed. Pass None to return to grid."""
        with self._lock:
            if feed_id is not None and feed_id not in self._feeds:
                print(f"[FeedManager] Feed {feed_id} not found.")
                return
            self._focused = feed_id

    def list_feeds(self):
        with self._lock:
            return list(self._feeds.keys())

    def list_feeds_with_config(self):
        """Return list of (feed_id, source, flip_h, flip_v, status) for all active feeds."""
        with self._lock:
            snapshot = {fid: stream for fid, stream in self._feeds.items()}
        result = []
        for fid, stream in snapshot.items():
            cfg = self._config.get_feed(fid) or {}
            result.append((
                fid,
                cfg.get('source', '?'),
                cfg.get('flip_h', False),
                cfg.get('flip_v', False),
                stream.status,
            ))
        return result

    def flip_feed(self, feed_id, flip_h=None, flip_v=None):
        """Toggle or set flip flags for a feed. Pass None to leave unchanged.

        Returns True on success, False if feed_id not found.
        """
        with self._lock:
            if feed_id not in self._feeds:
                return False
        # Toggle if no explicit value given
        cfg = self._config.get_feed(feed_id) or {}
        new_h = (not cfg.get('flip_h', False)) if flip_h is None else flip_h
        new_v = (not cfg.get('flip_v', False)) if flip_v is None else flip_v
        return self._config.update_flip(feed_id, flip_h=new_h, flip_v=new_v)

    def stop(self):
        """Stop all feeds, detection thread, and alert engine."""
        self._alert_engine.stop()
        self._designator.stop()
        with self._lock:
            for stream in self._feeds.values():
                stream.stop()
            self._feeds.clear()

    def _next_id(self):
        return max(self._feeds.keys(), default=-1) + 1

    # -------------------------------------------------------------------------
    # Data access for MainWindow
    # -------------------------------------------------------------------------

    def get_frames(self):
        """Return a dict of {feed_id: frame}.

        Live feeds are processed through the designator (overlays, detection).
        Non-live feeds (connecting / reconnecting / dead) return animated TV static
        — no face detection is run on noise.
        Frames are never None; callers can always render what they receive.
        """
        with self._lock:
            snapshot = {fid: stream for fid, stream in self._feeds.items()}

        processed = {}
        for fid, stream in snapshot.items():
            if stream.status == 'live':
                frame = stream.get_frame()
                if frame is not None:
                    frame = self._apply_flips(frame, fid)
                    frame = self._designator.process_frame(frame, fid)
                    processed[fid] = frame
                else:
                    # Briefly between frames — show static rather than a blank
                    processed[fid] = stream.get_static_frame()
            else:
                # Stream is connecting, reconnecting, or dead — show TV static
                processed[fid] = stream.get_static_frame()

        return processed

    def _apply_flips(self, frame, feed_id):
        """Apply horizontal and/or vertical flip based on per-feed config."""
        cfg = self._config.get_feed(feed_id)
        if cfg is None:
            return frame
        flip_h = cfg.get('flip_h', False)
        flip_v = cfg.get('flip_v', False)
        if flip_h and flip_v:
            return cv2.flip(frame, -1)   # both axes
        if flip_h:
            return cv2.flip(frame, 1)    # horizontal
        if flip_v:
            return cv2.flip(frame, 0)    # vertical
        return frame

    def get_raw_frames(self):
        """Return {feed_id: frame} without overlays — used for antispoof.

        Only returns frames from live streams to avoid running face detection
        on static noise.
        """
        with self._lock:
            result = {}
            for fid, stream in self._feeds.items():
                if stream.status == 'live':
                    f = stream.get_frame()
                    if f is not None:
                        result[fid] = f
        return result

    def get_focused(self):
        """Return the currently focused feed_id, or None for grid view."""
        with self._lock:
            return self._focused