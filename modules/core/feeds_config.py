# modules/core/feeds_config.py
# Persists per-feed configuration (source, flip flags) to config/feeds.json.
# Extend this file later for additional per-feed settings.

import json
import os

CONFIG_PATH = os.path.join('config', 'feeds.json')


class FeedsConfig:
    def __init__(self, path=CONFIG_PATH):
        self._path = path
        self._feeds = {}   # {feed_id: {source, flip_h, flip_v}}
        self._load()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_feed(self, feed_id):
        """Return config dict for a feed, or None if not found."""
        return self._feeds.get(feed_id)

    def get_all(self):
        """Return a copy of all feed configs as {feed_id: dict}."""
        return dict(self._feeds)

    def add_feed(self, feed_id, source, flip_h=False, flip_v=False):
        self._feeds[feed_id] = {
            'source': source,
            'flip_h': flip_h,
            'flip_v': flip_v,
        }
        self._save()

    def remove_feed(self, feed_id):
        if feed_id in self._feeds:
            del self._feeds[feed_id]
            self._save()

    def update_flip(self, feed_id, flip_h=None, flip_v=None):
        """Update flip flags for a feed. Pass None to leave unchanged."""
        if feed_id not in self._feeds:
            return False
        if flip_h is not None:
            self._feeds[feed_id]['flip_h'] = flip_h
        if flip_v is not None:
            self._feeds[feed_id]['flip_v'] = flip_v
        self._save()
        return True

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def _load(self):
        if not os.path.exists(self._path):
            self._feeds = {}
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # JSON keys are strings; convert feed IDs back to int
            self._feeds = {
                int(k): v for k, v in data.get('feeds', {}).items()
            }
        except Exception as e:
            print(f"[FeedsConfig] Failed to load config: {e}")
            self._feeds = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        try:
            data = {'feeds': {str(k): v for k, v in self._feeds.items()}}
            with open(self._path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[FeedsConfig] Failed to save config: {e}")