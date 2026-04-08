import sys

# Import onnxruntime-dependent libs BEFORE QApplication initializes
from insightface.app import FaceAnalysis

from PyQt5.QtWidgets import QApplication
from modules.core.startup import run
from modules.core.feed_manager import FeedManager
from modules.ui.main_window import MainWindow


def main():
    qt_app = QApplication(sys.argv)

    # Loading screen — blocks until warmup complete
    app, db, antispoof = run(qt_app)

    if app is None or db is None:
        sys.exit(1)

    manager = FeedManager(app, db)
    manager.add_feed(0)

    window = MainWindow(manager, db, antispoof)
    window.show()

    sys.exit(qt_app.exec_())


if __name__ == "__main__":
    main()