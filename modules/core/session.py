# modules/core/session.py
# Persists transient session state across process restarts.

import json
import os

SESSION_PATH = os.path.join('config', 'session.json')


def save(active_user_ssn=None, tracked_ssn=None, focused_feed_id=None, active_feeds=None):
    """Write session state to disk before restarting."""
    data = {
        'active_user_ssn': active_user_ssn,
        'tracked_ssn':     tracked_ssn,
        'focused_feed_id': focused_feed_id,
        'active_feeds':    active_feeds or [],
    }
    os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
    with open(SESSION_PATH, 'w') as f:
        json.dump(data, f)


def load():
    """Read session state written by a previous process.

    Returns a dict with keys: active_user_ssn, tracked_ssn, focused_feed_id, active_feeds.
    All values default to None / [] if not set or file missing.
    """
    empty = {
        'active_user_ssn': None,
        'tracked_ssn':     None,
        'focused_feed_id': None,
        'active_feeds':    [],
    }
    try:
        with open(SESSION_PATH) as f:
            data = json.load(f)
        return {**empty, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return empty


def clear():
    """Delete session file after it has been consumed."""
    try:
        os.remove(SESSION_PATH)
    except FileNotFoundError:
        pass