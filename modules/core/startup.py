# modules/core/startup.py
# Handles the loading screen and warmup of all modules before the main program starts.

import threading
import time
from datetime import datetime

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont

WINDOW_W, WINDOW_H = 1000, 600

STEPS = [
    "MACHINE.CORE.SYSTEM",
    "MACHINE.CORE.FEED_MANAGER",
    "MACHINE.IO.AUDIO",
    "MACHINE.IO.VIDEO_STREAM",
    "MACHINE.UI.INTERFACE",
    "MACHINE.PROFILER.FACIAL_DETECTION",
    "MACHINE.PROFILER.FACIAL_RECOGNITION",
    "MACHINE.PROFILER.THREAT_ASSESSMENT",
]

COL_WIDTH = 44


def _timestamp():
    return datetime.now().strftime("%H:%M:%S")


def _pad_dots(text):
    dots = COL_WIDTH - len(text)
    return text + "." * max(dots, 1)


class LoadingScreen(QWidget):
    _close_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._step_states = []
        self._lock = threading.Lock()
        self._dot_count = 0
        self._done = False
        self._result = {}
        self._sound_done = threading.Event()

        self._init_ui()

        self._close_signal.connect(self._on_warmup_complete)

        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(300)

        threading.Thread(target=self._warmup_wrapper, daemon=True).start()

    def _init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet("background-color: #000000;")

        layout = QVBoxLayout()
        layout.setContentsMargins(100, 50, 100, 50)
        layout.setSpacing(0)
        self.setLayout(layout)

        # Title
        title = QLabel("PROFILER MACHINE // SYSTEM INITIALIZATION")
        title.setFont(QFont("Courier New", 13))
        title.setStyleSheet("color: #ffffff;")
        layout.addWidget(title)

        # Divider
        divider = QLabel("=" * 74)
        divider.setFont(QFont("Courier New", 9))
        divider.setStyleSheet("color: #444444; margin-bottom: 16px;")
        layout.addWidget(divider)

        # Step labels
        self._step_labels = []
        for _ in STEPS:
            lbl = QLabel("")
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet("color: #ffffff;")
            lbl.setVisible(False)
            layout.addWidget(lbl)
            self._step_labels.append(lbl)

        layout.addStretch()

        # Footer
        self._footer_divider = QLabel("=" * 74)
        self._footer_divider.setFont(QFont("Courier New", 9))
        self._footer_divider.setStyleSheet("color: #444444;")
        self._footer_divider.setVisible(False)
        layout.addWidget(self._footer_divider)

        self._footer = QLabel("")
        self._footer.setFont(QFont("Courier New", 13))
        self._footer.setStyleSheet("color: #ffffff;")
        self._footer.setVisible(False)
        layout.addWidget(self._footer)

    def _on_warmup_complete(self):
        """Called on the main thread via signal — safe to stop timer and close."""
        self._timer.stop()
        self.close()

    def _refresh(self):
        self._dot_count += 1
        cursor = "_" if self._dot_count % 2 == 0 else " "

        with self._lock:
            states = list(self._step_states)
            done = self._done

        for i, state in enumerate(states):
            lbl = self._step_labels[i]
            padded = _pad_dots(state['text'])
            prefix = f"[{state['timestamp']}] "

            if state['status'] == 'ok':
                lbl.setText(f"{prefix}{padded}OK")
                lbl.setStyleSheet("color: #ffffff;")
            elif state['status'] == 'fail':
                lbl.setText(f"{prefix}{padded}FAIL")
                lbl.setStyleSheet("color: #ff0000;")
            else:
                lbl.setText(f"{prefix}{padded}{cursor}")
                lbl.setStyleSheet("color: #aaaaaa;")

            lbl.setVisible(True)

        if done:
            self._footer_divider.setVisible(True)
            self._footer.setText("ALL SYSTEMS OPERATIONAL")
            self._footer.setVisible(True)

    def _begin_step(self, name):
        with self._lock:
            self._step_states.append({
                'text': name,
                'timestamp': _timestamp(),
                'status': 'running'
            })

    def _complete_step(self):
        with self._lock:
            if self._step_states:
                self._step_states[-1]['status'] = 'ok'

    def _fail_step(self):
        with self._lock:
            if self._step_states:
                self._step_states[-1]['status'] = 'fail'

    def _has_failures(self):
        with self._lock:
            return any(s['status'] == 'fail' for s in self._step_states)

    def _warmup_wrapper(self):
        self._result['app'] = self._warmup()
        with self._lock:
            self._done = True

        # Wait for startup sound to finish before closing (max 10s)
        self._sound_done.wait(timeout=10)
        time.sleep(0.5)
        self._close_signal.emit()

    def _warmup(self):
        play_sound = None
        app = None

        # SYSTEM
        self._begin_step(STEPS[0])
        time.sleep(0.5)
        self._complete_step()

        # FEED_MANAGER
        self._begin_step(STEPS[1])
        time.sleep(0.5)
        self._complete_step()

        # AUDIO
        self._begin_step(STEPS[2])
        try:
            from modules.io.playsound import play_sound
            self._complete_step()
        except Exception as e:
            print(f"[{_timestamp()}] MACHINE.IO.AUDIO ERROR: {e}")
            self._fail_step()

        # VIDEO_STREAM
        self._begin_step(STEPS[3])
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            cap.release()
            self._complete_step()
        except Exception as e:
            print(f"[{_timestamp()}] MACHINE.IO.VIDEO_STREAM ERROR: {e}")
            self._fail_step()

        # INTERFACE
        self._begin_step(STEPS[4])
        time.sleep(0.5)
        self._complete_step()

        # FACIAL_DETECTION
        self._begin_step(STEPS[5])
        try:
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            self._complete_step()
        except Exception as e:
            print(f"[{_timestamp()}] MACHINE.PROFILER.FACIAL_DETECTION ERROR: {e}")
            self._fail_step()

        # FACIAL_RECOGNITION — only attempt if detection succeeded
        self._begin_step(STEPS[6])
        if app is not None:
            try:
                app.prepare(ctx_id=0, det_size=(640, 640))
                self._complete_step()
            except Exception as e:
                print(f"[{_timestamp()}] MACHINE.PROFILER.FACIAL_RECOGNITION ERROR: {e}")
                self._fail_step()
        else:
            self._fail_step()

        # THREAT_ASSESSMENT
        self._begin_step(STEPS[7])
        time.sleep(0.5)
        self._complete_step()

        # Check for failures
        if self._has_failures():
            print(f"[{_timestamp()}] System initialization failed. Exiting...")
            time.sleep(2.0)
            self._sound_done.set()  # unblock _warmup_wrapper so it can close
            return None

        # Play startup sound and wait for it to finish
        if play_sound is not None:
            def _play_and_signal():
                play_sound("assets/audio/startup.wav")
                self._sound_done.set()

            threading.Thread(target=_play_and_signal, daemon=True).start()
        else:
            self._sound_done.set()  # no sound, unblock immediately

        return app

    def get_app(self):
        return self._result.get('app')


def run(qt_app):
    """
    Show the loading screen and block until warmup is complete.
    Returns the initialized FaceAnalysis app.
    qt_app: the QApplication instance created in main.py
    """
    screen = LoadingScreen()

    geo = qt_app.desktop().screenGeometry()
    screen.move(
        (geo.width() - WINDOW_W) // 2,
        (geo.height() - WINDOW_H) // 2
    )

    screen.show()
    qt_app.exec_()

    return screen.get_app()