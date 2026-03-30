# modules/ui/main_window.py
# Main application window — displays video feeds with a custom title bar.

import cv2
import math
import numpy as np

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap, QKeySequence

WINDOW_W, WINDOW_H = 1000, 600
TITLE_BAR_H = 32
FEED_AREA_H = WINDOW_H - TITLE_BAR_H


class TitleBar(QWidget):
    """Custom draggable title bar."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self._drag_pos = None

        self.setFixedHeight(TITLE_BAR_H)
        self.setStyleSheet("background-color: #111111;")

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        self.setLayout(layout)

        # Title
        title = QLabel("PROFILER MACHINE")
        title.setFont(QFont("Courier New", 10))
        title.setStyleSheet("color: #ffffff;")
        layout.addWidget(title)

        layout.addStretch()

        # Hint
        hint = QLabel("ALT+X — console")
        hint.setFont(QFont("Courier New", 8))
        hint.setStyleSheet("color: #444444;")
        layout.addWidget(hint)

        # Fullscreen button
        self._btn_fullscreen = QPushButton("[ ]")
        self._btn_fullscreen.setFont(QFont("Courier New", 9))
        self._btn_fullscreen.setFixedSize(36, 22)
        self._btn_fullscreen.setStyleSheet(self._btn_style())
        self._btn_fullscreen.clicked.connect(parent.toggle_fullscreen)
        layout.addWidget(self._btn_fullscreen)

        # Minimize button
        btn_min = QPushButton("—")
        btn_min.setFont(QFont("Courier New", 9))
        btn_min.setFixedSize(36, 22)
        btn_min.setStyleSheet(self._btn_style())
        btn_min.clicked.connect(parent.showMinimized)
        layout.addWidget(btn_min)

        # Close button
        btn_close = QPushButton("✕")
        btn_close.setFont(QFont("Courier New", 9))
        btn_close.setFixedSize(36, 22)
        btn_close.setStyleSheet(self._btn_style(close=True))
        btn_close.clicked.connect(parent.close)
        layout.addWidget(btn_close)

    def _btn_style(self, close=False):
        hover = "#cc0000" if close else "#333333"
        return f"""
            QPushButton {{
                background-color: #1a1a1a;
                color: #aaaaaa;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {hover};
                color: #ffffff;
            }}
        """

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.parent.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.parent.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class FeedDisplay(QLabel):
    """Widget that displays the video feed grid or a focused feed."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #000000;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._show_placeholder()

    def _show_placeholder(self):
        w, h = WINDOW_W, FEED_AREA_H
        img = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(img, "NO ACTIVE FEEDS", (w // 2 - 140, h // 2),
                    cv2.FONT_HERSHEY_COMPLEX, 0.8, (60, 60, 60), 1)
        self._set_frame(img)

    def _set_frame(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(qt_img).scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    def update_frame(self, frame_bgr):
        self._set_frame(frame_bgr)


class MainWindow(QWidget):
    def __init__(self, feed_manager):
        super().__init__()
        self.feed_manager = feed_manager
        self._is_fullscreen = False
        self._console = None  # set after construction via set_console()

        self._init_ui()

        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(33)

    def set_console(self, console):
        """Attach the console after construction."""
        self._console = console

    def _init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet("background-color: #000000;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        self._title_bar = TitleBar(self)
        layout.addWidget(self._title_bar)

        self._feed_display = FeedDisplay()
        layout.addWidget(self._feed_display)

    def toggle_fullscreen(self):
        if self._is_fullscreen:
            self.setWindowFlags(Qt.FramelessWindowHint)
            self.setFixedSize(WINDOW_W, WINDOW_H)
            self._title_bar.setVisible(True)
            self.showNormal()
            self._is_fullscreen = False
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setFixedSize(
                self.screen().size().width(),
                self.screen().size().height()
            )
            self._title_bar.setVisible(False)
            self.showFullScreen()
            self._is_fullscreen = True

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.AltModifier and event.key() == Qt.Key_X:
            if self._console:
                self._console.toggle()
        else:
            super().keyPressEvent(event)

    def _refresh(self):
        frames = self.feed_manager.get_frames()

        if not frames:
            self._feed_display._show_placeholder()
            return

        focused_id = self.feed_manager.get_focused()

        if focused_id is not None and focused_id in frames and frames[focused_id] is not None:
            self._feed_display.update_frame(frames[focused_id].copy())
        else:
            grid = self._render_grid(frames)
            self._feed_display.update_frame(grid)

    def _render_grid(self, frames):
        feed_ids = list(frames.keys())
        count = len(feed_ids)

        if count == 1:
            fid = feed_ids[0]
            frame = frames[fid]
            if frame is None:
                blank = np.zeros((FEED_AREA_H, WINDOW_W, 3), dtype=np.uint8)
                cv2.putText(blank, f"FEED {fid} — WAITING", (10, FEED_AREA_H // 2),
                            cv2.FONT_HERSHEY_COMPLEX, 0.5, (100, 100, 100), 1)
                return blank
            cell = frame.copy()
            cv2.putText(cell, f"FEED {fid}", (8, 22),
                        cv2.FONT_HERSHEY_COMPLEX, 0.55, (255, 255, 255), 1)
            return cell

        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)
        cw, ch = WINDOW_W // cols, FEED_AREA_H // rows
        grid = np.zeros((rows * ch, cols * cw, 3), dtype=np.uint8)

        for idx, fid in enumerate(feed_ids):
            row = idx // cols
            col = idx % cols
            x, y = col * cw, row * ch
            frame = frames[fid]

            if frame is None:
                cell = np.zeros((ch, cw, 3), dtype=np.uint8)
                cv2.putText(cell, f"FEED {fid} — WAITING", (10, ch // 2),
                            cv2.FONT_HERSHEY_COMPLEX, 0.5, (100, 100, 100), 1)
            else:
                cell = cv2.resize(frame, (cw, ch))
                cv2.putText(cell, f"FEED {fid}", (8, 22),
                            cv2.FONT_HERSHEY_COMPLEX, 0.55, (255, 255, 255), 1)
                cv2.rectangle(cell, (0, 0), (cw - 1, ch - 1), (40, 40, 40), 1)

            grid[y:y + ch, x:x + cw] = cell

        return grid

    def closeEvent(self, event):
        self._timer.stop()
        self.feed_manager.stop()
        if self._console:
            self._console.hide()
        event.accept()