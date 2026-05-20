import sys

# Import onnxruntime-dependent libs BEFORE QApplication initializes
from insightface.app import FaceAnalysis

from PyQt5.QtWidgets import QApplication
from modules.core.startup import run
from modules.core.feed_manager import FeedManager
from modules.ui.main_window import MainWindow
from modules.ui.device_picker import pick_devices


def main():
    qt_app = QApplication(sys.argv)

    # Loading screen — blocks until warmup complete.
    # Device scan runs silently in the background during warmup.
    app, db, antispoof, body_detector, devices = run(qt_app)

    if app is None or db is None:
        sys.exit(1)

    manager = FeedManager(app, db, body_detector=body_detector)

    # Show device picker — operator selects which feeds to initialize.
    selected = pick_devices(devices)
    if selected:
        for dev in selected:
            manager.add_feed(dev['index'])
    else:
        # Operator skipped selection — restore feed ID 0 from saved config,
        # or fall back to device index 0 if no config exists yet.
        saved = manager._config.get_all()
        if saved and 0 in saved:
            entry = saved[0]
            src = entry.get('source', 0)
            # JSON stores everything as strings; coerce back to int for local devices.
            if isinstance(src, str) and src.isdigit():
                src = int(src)
            manager.add_feed(src)
        else:
            manager.add_feed(0)

    window = MainWindow(manager, db, antispoof)
    window.show()

    sys.exit(qt_app.exec_())


if __name__ == "__main__":
    main()