# modules/core/feed_manager.py
# Manages multiple video streams and their state.

import threading
from modules.io.videostream import VideoStream
from modules.profiler.designation import Designator
from modules.profiler.alerts import AlertEngine


class FeedManager:
    def __init__(self, app, db, body_detector=None):
        self.app = app
        self.db = db
        self._feeds = {}
        self._lock = threading.Lock()
        self._focused = None
        self._designator = Designator(app, db, body_detector=body_detector)

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

    def _console_print(self, text, ok=True):
        if self._console_cb:
            self._console_cb(text, ok=ok)

    def _play_sound(self, path):
        try:
            from modules.io.playsound import play_sound
            play_sound(path)
        except Exception as e:
            print(f"[FeedManager] Sound error: {e}")

    # -------------------------------------------------------------------------
    # Feed management
    # -------------------------------------------------------------------------

    def add_feed(self, source):
        """Add a new feed. Returns the feed_id assigned to it."""
        with self._lock:
            feed_id = self._next_id()
            stream = VideoStream(source)
            stream.start()
            self._feeds[feed_id] = stream
            print(f"[FeedManager] Added feed {feed_id}: {source}")
            return feed_id

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
        """Return a dict of {feed_id: frame} with overlays and alert cards applied."""
        with self._lock:
            raw = {fid: (stream.get_frame(), fid) for fid, stream in self._feeds.items()}

        processed = {}
        for fid, (frame, feed_id) in raw.items():
            if frame is not None:
                frame = self._designator.process_frame(frame, feed_id)
                processed[fid] = frame
            else:
                processed[fid] = None

        return processed

    def get_raw_frames(self):
        """Return a dict of {feed_id: frame} without overlays — used for antispoof."""
        with self._lock:
            return {fid: stream.get_frame() for fid, stream in self._feeds.items()}

    def get_focused(self):
        """Return the currently focused feed_id, or None for grid view."""
        with self._lock:
            return self._focused