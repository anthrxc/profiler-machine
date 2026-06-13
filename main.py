import sys
import os
import subprocess
import atexit

# Install stdout/stderr intercept FIRST — captures all print() output from here on.
from modules.core.logger import get_logger as _get_logger
_logger = _get_logger()
_logger.install_intercept()
_logger.open_log_file(os.path.join('logs', 'profiler_machine.log'))

# Import onnxruntime-dependent libs BEFORE QApplication initializes
from insightface.app import FaceAnalysis

from PyQt5.QtWidgets import QApplication
from modules.core.startup import run
from modules.core.feed_manager import FeedManager
from modules.core.feeds_config import FeedsConfig
from modules.core import session
from modules.ui.main_window import MainWindow
from modules.ui.device_picker import pick_devices


def _coerce_source(src):
    """Convert string digit sources back to int (device index)."""
    if isinstance(src, str) and src.isdigit():
        return int(src)
    return src


def main():
    restore = '--restore' in sys.argv

    qt_app = QApplication(sys.argv)

    # Loading screen — blocks until warmup complete.
    app, db, antispoof, body_detector, devices = run(qt_app, restore=restore)

    if app is None or db is None:
        sys.exit(1)

    manager = FeedManager(app, db, body_detector=body_detector)

    if restore:
        sess_feeds = session.load().get('active_feeds', [])
        if sess_feeds:
            for entry in sess_feeds:
                manager.add_feed(
                    _coerce_source(entry.get('source', 0)),
                    flip_h=entry.get('flip_h', False),
                    flip_v=entry.get('flip_v', False),
                )
        else:
            manager.add_feed(0)
    else:
        saved = manager._config.get_all()
        if saved:
            # Auto-load every feed previously added — skip the picker.
            for feed_id in sorted(saved.keys()):
                entry = saved[feed_id]
                manager.add_feed(
                    _coerce_source(entry.get('source', 0)),
                    flip_h=entry.get('flip_h', False),
                    flip_v=entry.get('flip_v', False),
                )
        else:
            # First run — no saved feeds; show the picker.
            selected = pick_devices(devices)
            if selected:
                for dev in selected:
                    manager.add_feed(dev['index'])
            else:
                manager.add_feed(0)

    # ── Web API ───────────────────────────────────────────────────────────────
    # Internal REST API runs as a daemon thread inside this process (port 5001).
    # Mobile web server runs as a separate subprocess (port 8000).
    try:
        import json as _json
        _api_port = 5001
        try:
            with open(os.path.join('config', 'web.json'), 'r', encoding='utf-8') as _fh:
                _api_port = _json.load(_fh).get('internal_api_port', 5001)
        except Exception:
            pass
        from modules.api.internal_api import start_internal_api
        start_internal_api(manager, db, port=_api_port)
    except Exception as e:
        print(f'[main] Failed to start internal API: {e}')

    try:
        _web_server_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'web', 'server.py'
        )
        _web_proc = subprocess.Popen(
            [sys.executable, _web_server_path, '--parent-pid', str(os.getpid())],
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        atexit.register(_web_proc.terminate)
        print(f'[main] Web server spawned (PID {_web_proc.pid}) on port 8000')
    except Exception as e:
        print(f'[main] Failed to spawn web server: {e}')
    # ─────────────────────────────────────────────────────────────────────────

    sess = session.load() if restore else {}
    session.clear()

    window = MainWindow(manager, db, antispoof, session=sess)
    window.show()

    sys.exit(qt_app.exec_())


if __name__ == "__main__":
    main()