import sys

# Import onnxruntime-dependent libs BEFORE QApplication initializes
from insightface.app import FaceAnalysis

from PyQt5.QtWidgets import QApplication
from modules.core.startup import run
from modules.core.feed_manager import FeedManager
from modules.ui.main_window import MainWindow
from modules.ui.console import Console


def main():
    qt_app = QApplication(sys.argv)

    # Loading screen — blocks until warmup complete
    app = run(qt_app)

    if app is None:
        sys.exit(1)

    # Set up feed manager and add default webcam feed
    manager = FeedManager(app)
    manager.add_feed(0)

    # Create main window and console, wire them together
    window = MainWindow(manager)
    console = Console(window, manager)
    window.set_console(console)

    window.show()

    sys.exit(qt_app.exec_())


if __name__ == "__main__":
    main()