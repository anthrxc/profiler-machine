import sys

# Import onnxruntime-dependent libs BEFORE QApplication initializes
from insightface.app import FaceAnalysis

from PyQt5.QtWidgets import QApplication
from modules.core.startup import run


def main():
    qt_app = QApplication(sys.argv)
    app = run(qt_app)
    # main_window and console will be initialized here next


if __name__ == "__main__":
    main()