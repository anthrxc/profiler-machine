# modules/core/feed_manager.py
# Manages multiple video streams and their state.

import threading
from modules.io.videostream import VideoStream
from modules.profiler.designation import Designator


class FeedManager:
    def __init__(self, app, db):
        self.app = app
        self.db = db
        self._feeds = {}
        self._lock = threading.Lock()
        self._focused = None
        self._designator = Designator(app, db)

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
        """Stop all feeds and the detection thread."""
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
        """Return a dict of {feed_id: frame} with overlays applied."""
        with self._lock:
            raw = {fid: (stream.get_frame(), fid) for fid, stream in self._feeds.items()}

        processed = {}
        for fid, (frame, feed_id) in raw.items():
            if frame is not None:
                processed[fid] = self._designator.process_frame(frame, feed_id)
            else:
                processed[fid] = None

        return processed

    def get_focused(self):
        """Return the currently focused feed_id, or None for grid view."""
        with self._lock:
            return self._focused