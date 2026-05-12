# modules/core/startup.py
# Handles the loading screen and warmup of all modules before the main program starts.

import threading
import time
import os
import ctypes
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
    "MACHINE.PROFILER.BODY_DETECTION",
    "MACHINE.PROFILER.DATABASE",
    "MACHINE.PROFILER.AUTO_ENROLL",
    "MACHINE.PROFILER.ANTISPOOF",
    "MACHINE.PROFILER.THREAT_ASSESSMENT",
]

COL_WIDTH = 44

CUDA_PATH = r"C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v12.8\\bin"
CUDNN_PATH = r"C:\\Program Files\\NVIDIA\CUDNN\\v9.20\\bin\\12.9\\x64"

ANTISPOOF_MODEL_PATH = os.path.join('assets', 'antispoof', 'MiniFASNetV2.onnx')


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

        title = QLabel("PROFILER MACHINE // SYSTEM INITIALIZATION")
        title.setFont(QFont("Courier New", 13))
        title.setStyleSheet("color: #ffffff;")
        layout.addWidget(title)

        divider = QLabel("=" * 74)
        divider.setFont(QFont("Courier New", 9))
        divider.setStyleSheet("color: #444444; margin-bottom: 16px;")
        layout.addWidget(divider)

        self._step_labels = []
        for _ in STEPS:
            lbl = QLabel("")
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet("color: #ffffff;")
            lbl.setVisible(False)
            layout.addWidget(lbl)
            self._step_labels.append(lbl)

        layout.addStretch()

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
        (self._result['app'], self._result['db'],
         self._result['antispoof'], self._result['body_detector'],
         self._result['devices']) = self._warmup()
        with self._lock:
            self._done = True
        self._sound_done.wait(timeout=10)
        time.sleep(0.5)
        self._close_signal.emit()

    def _warmup(self):
        play_sound = None
        app = None
        db = None
        antispoof = None
        body_detector = None
        devices = []

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

        # VIDEO_STREAM — open a test capture AND silently scan all devices
        self._begin_step(STEPS[3])
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            cap.release()
            # Scan for available devices in the background while warmup continues.
            # Results are ready by the time the loading screen closes.
            from modules.core.device_enumerator import enumerate_devices
            import threading as _threading
            _scan_done = threading.Event()
            def _scan():
                nonlocal devices
                devices = enumerate_devices()
                _scan_done.set()
            _threading.Thread(target=_scan, daemon=True).start()
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
            os.add_dll_directory(CUDA_PATH)
            ctypes.WinDLL(os.path.join(CUDA_PATH, "nvrtc-builtins64_128.dll"))
            import onnxruntime as ort
            ort.preload_dlls(cuda=True, cudnn=False, msvc=True, directory=CUDA_PATH)
            ort.preload_dlls(cuda=False, cudnn=True, directory=CUDNN_PATH)

            from insightface.app import FaceAnalysis
            app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
            self._complete_step()
        except Exception as e:
            print(f"[{_timestamp()}] MACHINE.PROFILER.FACIAL_DETECTION ERROR: {e}")
            self._fail_step()

        # FACIAL_RECOGNITION
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

        # BODY_DETECTION
        # Loaded here, before QApplication owns the main thread, for the same
        # CUDA-DLL-ordering reason as InsightFace. A failure here is non-fatal
        # — the Designator degrades gracefully to face-only tracking.
        self._begin_step(STEPS[7])
        try:
            from modules.profiler.body_detector import BodyDetector
            body_detector = BodyDetector()
            ok = body_detector.load()
            if ok:
                self._complete_step()
            else:
                body_detector = None
                self._fail_step()
        except Exception as e:
            print(f"[{_timestamp()}] MACHINE.PROFILER.BODY_DETECTION ERROR: {e}")
            body_detector = None
            self._fail_step()

        # DATABASE
        self._begin_step(STEPS[8])
        try:
            from modules.profiler.recognition import RecognitionDB
            db = RecognitionDB()
            db.connect()
            count = db.count()
            self._complete_step()
            print(f"[{_timestamp()}] Database loaded: {count} person(s) on record.")
        except Exception as e:
            print(f"[{_timestamp()}] MACHINE.PROFILER.DATABASE ERROR: {e}")
            self._fail_step()

        # AUTO_ENROLL
        self._begin_step(STEPS[9])
        if db is not None and app is not None:
            try:
                results = db.enroll_startup_images(app)
                if results:
                    for filename, ssn, success, message in results:
                        if success:
                            print(f"[{_timestamp()}] Auto-enrolled '{filename}' → {ssn} ({message})")
                        else:
                            print(f"[{_timestamp()}] Failed to enroll '{filename}': {message}")
                self._complete_step()
            except Exception as e:
                print(f"[{_timestamp()}] MACHINE.PROFILER.AUTO_ENROLL ERROR: {e}")
                self._fail_step()
        else:
            self._fail_step()

        # ANTISPOOF
        self._begin_step(STEPS[10])
        try:
            from modules.profiler.antispoof import AntiSpoofModel
            antispoof = AntiSpoofModel(ANTISPOOF_MODEL_PATH)
            self._complete_step()
        except Exception as e:
            print(f"[{_timestamp()}] MACHINE.PROFILER.ANTISPOOF ERROR: {e}")
            self._fail_step()

        # THREAT_ASSESSMENT
        self._begin_step(STEPS[11])
        time.sleep(0.5)
        self._complete_step()

        # Check for failures — body detector failure is tolerated (degrades to
        # face-only) so we don't abort startup on its account.
        if self._has_failures_excluding_body():
            print(f"[{_timestamp()}] System initialization failed. Exiting...")
            time.sleep(2.0)
            self._sound_done.set()
            return None, None, None, None

        if play_sound is not None:
            def _play_and_signal():
                play_sound("assets/audio/startup.wav")
                self._sound_done.set()
            threading.Thread(target=_play_and_signal, daemon=True).start()
        else:
            self._sound_done.set()

        # Ensure device scan is complete before we return
        try:
            _scan_done.wait(timeout=15)
        except Exception:
            pass

        return app, db, antispoof, body_detector, devices

    def _has_failures_excluding_body(self):
        """A failed body detector is non-fatal — the Designator degrades to face-only."""
        with self._lock:
            for s in self._step_states:
                if s['status'] == 'fail' and s['text'] != 'MACHINE.PROFILER.BODY_DETECTION':
                    return True
            return False

    def get_app(self):
        return self._result.get('app')

    def get_db(self):
        return self._result.get('db')

    def get_antispoof(self):
        return self._result.get('antispoof')

    def get_body_detector(self):
        return self._result.get('body_detector')

    def get_devices(self):
        return self._result.get('devices', [])


def run(qt_app):
    screen = LoadingScreen()

    geo = qt_app.desktop().screenGeometry()
    screen.move(
        (geo.width() - WINDOW_W) // 2,
        (geo.height() - WINDOW_H) // 2
    )

    screen.show()
    qt_app.exec_()

    return (screen.get_app(), screen.get_db(),
            screen.get_antispoof(), screen.get_body_detector(),
            screen.get_devices())