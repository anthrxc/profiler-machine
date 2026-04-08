# modules/ui/main_window.py
# Main application window with docked console and profiler panel.

import cv2
import math
import time
import os
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QScrollArea, QLineEdit, QFrame
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap

from modules.profiler.recognition import DESIGNATIONS, IMAGES_DIR
from modules.ui.profiler_panel import ProfilerPanel, PANEL_W

WINDOW_W        = 1000
FEED_H          = 568
TITLE_BAR_H     = 32
CONSOLE_H       = 200
WINDOW_H        = TITLE_BAR_H + FEED_H + CONSOLE_H

AUTH_TIMEOUT    = 3.0


# ─────────────────────────────────────────────────────────────────────────────
# Title bar
# ─────────────────────────────────────────────────────────────────────────────

class TitleBar(QWidget):
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

        title = QLabel("PROFILER MACHINE")
        title.setFont(QFont("Courier New", 10))
        title.setStyleSheet("color: #ffffff;")
        layout.addWidget(title)

        layout.addStretch()

        for label, slot, close in [("[ ]", parent.toggle_fullscreen, False),
                                    ("—",   parent.showMinimized,    False),
                                    ("✕",   parent.close,            True)]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9))
            btn.setFixedSize(36, 22)
            btn.setStyleSheet(self._btn_style(close))
            btn.clicked.connect(slot)
            layout.addWidget(btn)

    def _btn_style(self, close=False):
        hover = "#cc0000" if close else "#333333"
        return f"""
            QPushButton {{ background-color: #1a1a1a; color: #aaaaaa; border: none; }}
            QPushButton:hover {{ background-color: {hover}; color: #ffffff; }}
        """

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.parent.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._drag_pos:
            self.parent.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


# ─────────────────────────────────────────────────────────────────────────────
# Feed display
# ─────────────────────────────────────────────────────────────────────────────

class FeedDisplay(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #000000;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _set_frame(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self.setPixmap(QPixmap.fromImage(qt_img).scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    def show_placeholder(self):
        img = np.zeros((self.height() or FEED_H, self.width() or WINDOW_W, 3), dtype=np.uint8)
        w, h = img.shape[1], img.shape[0]
        cv2.putText(img, "NO ACTIVE FEEDS", (w // 2 - 140, h // 2),
                    cv2.FONT_HERSHEY_COMPLEX, 0.8, (60, 60, 60), 1)
        self._set_frame(img)

    def update_frame(self, frame_bgr):
        self._set_frame(frame_bgr)


# ─────────────────────────────────────────────────────────────────────────────
# Console widget (docked, always visible)
# ─────────────────────────────────────────────────────────────────────────────

class ConsoleWidget(QWidget):
    def __init__(self, feed_manager, db, main_window, antispoof=None):
        super().__init__()
        self.feed_manager = feed_manager
        self.db = db
        self._main_window = main_window
        self._antispoof = antispoof

        self._active_user_ssn = None
        self._last_seen_time = None
        self._logout_timer = QTimer()
        self._logout_timer.timeout.connect(self._check_auth_timeout)
        self._logout_timer.start(500)

        self._history = []
        self._history_index = -1
        self._awaiting_name_for_ssn = None

        self.setFixedHeight(CONSOLE_H)
        self.setStyleSheet("background-color: #0a0a0a;")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #222222;")
        layout.addWidget(divider)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: #0a0a0a; }
            QScrollBar:vertical { background: #111111; width: 6px; }
            QScrollBar::handle:vertical { background: #333333; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        self._history_container = QWidget()
        self._history_container.setStyleSheet("background-color: #0a0a0a;")
        self._history_layout = QVBoxLayout()
        self._history_layout.setContentsMargins(10, 4, 10, 4)
        self._history_layout.setSpacing(1)
        self._history_layout.addStretch()
        self._history_container.setLayout(self._history_layout)
        self._scroll.setWidget(self._history_container)
        layout.addWidget(self._scroll)

        input_row = QWidget()
        input_row.setFixedHeight(30)
        input_row.setStyleSheet("background-color: #111111;")
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(10, 0, 10, 0)
        input_layout.setSpacing(6)
        input_row.setLayout(input_layout)

        self._prompt_label = QLabel(">")
        self._prompt_label.setFont(QFont("Courier New", 10))
        self._prompt_label.setStyleSheet("color: #ffffff;")
        input_layout.addWidget(self._prompt_label)

        self._input = QLineEdit()
        self._input.setFont(QFont("Courier New", 10))
        self._input.setStyleSheet("""
            QLineEdit {
                background-color: #111111;
                color: #ffffff;
                border: none;
                selection-background-color: #333333;
            }
        """)
        self._input.returnPressed.connect(self._on_submit)
        self._input.installEventFilter(self)
        input_layout.addWidget(self._input)

        layout.addWidget(input_row)

        status_bar = QWidget()
        status_bar.setFixedHeight(24)
        status_bar.setStyleSheet("background-color: #0d0d0d; border-top: 1px solid #1a1a1a;")
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_bar.setLayout(status_layout)

        self._status_user = QLabel("USER: —")
        self._status_user.setFont(QFont("Courier New", 8))
        self._status_user.setStyleSheet("color: #555555;")
        status_layout.addWidget(self._status_user)

        status_layout.addWidget(self._make_sep())

        self._status_feeds = QLabel("FEEDS: 0")
        self._status_feeds.setFont(QFont("Courier New", 8))
        self._status_feeds.setStyleSheet("color: #555555;")
        status_layout.addWidget(self._status_feeds)

        status_layout.addWidget(self._make_sep())

        self._status_persons = QLabel("PERSONS: 0")
        self._status_persons.setFont(QFont("Courier New", 8))
        self._status_persons.setStyleSheet("color: #555555;")
        status_layout.addWidget(self._status_persons)

        status_layout.addWidget(self._make_sep())

        self._status_auth = QLabel("")
        self._status_auth.setFont(QFont("Courier New", 8))
        self._status_auth.setStyleSheet("color: #555555;")
        status_layout.addWidget(self._status_auth)

        status_layout.addStretch()
        layout.addWidget(status_bar)

        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1000)

    def _make_sep(self):
        sep = QLabel("  |  ")
        sep.setFont(QFont("Courier New", 8))
        sep.setStyleSheet("color: #222222;")
        return sep

    def focus_input(self):
        self._input.setFocus()

    # -------------------------------------------------------------------------
    # History
    # -------------------------------------------------------------------------

    def _add_line(self, text, color="#aaaaaa"):
        ts = time.strftime("%H:%M:%S")
        lbl = QLabel(f"[{ts}]  {text}")
        lbl.setFont(QFont("Courier New", 9))
        lbl.setStyleSheet(f"color: {color}; padding: 0px;")
        lbl.setWordWrap(True)
        self._history_layout.insertWidget(self._history_layout.count() - 1, lbl)
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _print(self, text, ok=True):
        self._add_line(text, "#cccccc" if ok else "#ff4444")

    def _print_input(self, text):
        self._add_line(f"> {text}", "#ffffff")

    # -------------------------------------------------------------------------
    # Status bar
    # -------------------------------------------------------------------------

    def _refresh_status(self):
        self._status_feeds.setText(f"FEEDS: {len(self.feed_manager.list_feeds())}")
        self._status_persons.setText(f"PERSONS: {self.db.count()}")

        if self._active_user_ssn:
            person = self.db.get_by_ssn(self._active_user_ssn)
            if person:
                name = person[2] or self._active_user_ssn
                self._status_user.setText(f"USER: {name} [{person[3].upper()}]")
                self._status_user.setStyleSheet("color: #88ff88;")
            if self._last_seen_time is not None:
                remaining = max(0, AUTH_TIMEOUT - (time.time() - self._last_seen_time))
                self._status_auth.setText(f"logout in {remaining:.0f}s" if remaining > 0 else "")
                self._status_auth.setStyleSheet("color: #ffaa44;")
            else:
                self._status_auth.setText("")
        else:
            self._status_user.setText("USER: —")
            self._status_user.setStyleSheet("color: #555555;")
            self._status_auth.setText("")

    # -------------------------------------------------------------------------
    # Auth
    # -------------------------------------------------------------------------

    def _check_auth_timeout(self):
        if self._active_user_ssn is None:
            return
        in_frame = self.feed_manager._designator.is_ssn_in_frame(self._active_user_ssn)
        if in_frame:
            self._last_seen_time = None
        else:
            if self._last_seen_time is None:
                self._last_seen_time = time.time()
            elif time.time() - self._last_seen_time >= AUTH_TIMEOUT:
                self._print(f"Session expired — {self._active_user_ssn} no longer in frame.", ok=False)
                self._active_user_ssn = None
                self._last_seen_time = None

    def _is_root(self):
        if not self._active_user_ssn:
            return False
        person = self.db.get_by_ssn(self._active_user_ssn)
        return person and person[3] == 'root'

    # -------------------------------------------------------------------------
    # Key events
    # -------------------------------------------------------------------------

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if obj == self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                if self._history and self._history_index < len(self._history) - 1:
                    self._history_index += 1
                    self._input.setText(self._history[-(self._history_index + 1)])
                return True
            elif event.key() == Qt.Key_Down:
                if self._history_index > 0:
                    self._history_index -= 1
                    self._input.setText(self._history[-(self._history_index + 1)])
                elif self._history_index == 0:
                    self._history_index = -1
                    self._input.clear()
                return True
        return super().eventFilter(obj, event)

    # -------------------------------------------------------------------------
    # Command handling
    # -------------------------------------------------------------------------

    def _on_submit(self):
        text = self._input.text().strip()
        self._input.clear()
        self._history_index = -1
        if not text:
            return

        if self._awaiting_name_for_ssn:
            ssn = self._awaiting_name_for_ssn
            self._awaiting_name_for_ssn = None
            self._prompt_label.setText(">")
            self._print_input(text)
            if text.lower() == 'skip':
                self._print(f"Name skipped for {ssn}.")
            else:
                self.db.update_person(ssn, 'name', text)
                self._print(f"Name set to '{text}' for {ssn}.")
            return

        self._history.append(text)
        self._print_input(text)
        self._handle_command(text)

    def _handle_command(self, cmd):
        parts = cmd.strip().split()
        primary = parts[0].lower()
        args = parts[1:]

        if primary == "quit":
            self._print("SHUTTING DOWN...")
            self._main_window.close()

        elif primary == "help":
            self._print("using <SSN> | quit | fullscreen | overlay [role]")
            self._print("feed [add/remove/focus/grid/list]")
            self._print("profiler [toggle/start/stop/show/enroll/remove/update/list/info]")

        elif primary == "fullscreen":
            self._main_window.toggle_fullscreen()
            self._print("Toggled fullscreen.")

        elif primary == "using":
            self._handle_using(args)

        elif primary == "overlay":
            if not args:
                self._print(f"Roles: {', '.join(DESIGNATIONS)}", ok=False)
                return
            success = self.feed_manager._designator.set_debug_role(args[0].lower())
            self._print(f"Debug overlay: {args[0]}" if success else f"Unknown role: '{args[0]}'", ok=success)

        elif primary == "feed":
            if not args:
                self._print("Usage: feed [add/remove/focus/grid/list]", ok=False)
                return
            self._handle_feed(args)

        elif primary == "profiler":
            if not args:
                self._print("Usage: profiler [toggle/start/stop/show/enroll/remove/update/list/info]", ok=False)
                return
            self._handle_profiler(args)

        else:
            self._print(f"Unknown command: '{primary}'", ok=False)

    def _handle_using(self, args):
        if not args:
            self._print("Usage: using <SSN>", ok=False)
            return
        ssn = args[0]
        person = self.db.get_by_ssn(ssn)
        if not person:
            self._print(f"No person found: {ssn}", ok=False)
            return
        if person[3] not in ('root', 'admin'):
            self._print(f"Access denied — {ssn} does not have elevated privileges.", ok=False)
            return
        if not self.feed_manager._designator.is_ssn_in_frame(ssn):
            self._print(f"Authentication failed — {ssn} not detected in any active feed.", ok=False)
            return

        # Anti-spoof check
        if self._antispoof is not None:
            self._print("Running liveness check...")
            designator = self.feed_manager._designator
            with designator._lock:
                results = list(designator._latest_results)
            # Find the bbox for this SSN
            bbox = None
            for r in results:
                if r.get('ssn') == ssn:
                    bbox = r.get('bbox')
                    break
            if bbox is None:
                self._print("Authentication failed — could not locate face in frame.", ok=False)
                return
            # Get the latest raw frame
            frames = self.feed_manager.get_raw_frames()
            frame = next(iter(frames.values()), None) if frames else None
            if frame is None:
                self._print("Authentication failed — no frame available.", ok=False)
                return
            result = self._antispoof.predict_from_bbox(frame, bbox)
            if not result['ok']:
                self._print("Authentication failed — liveness check error.", ok=False)
                return
            if not result['is_live']:
                self._print(f"Authentication failed — spoofing detected (score: {result['score']:.2f}).", ok=False)
                return
            self._print(f"Liveness confirmed (score: {result['score']:.2f}).")

        self._active_user_ssn = ssn
        self._last_seen_time = None
        self._print(f"Authenticated as {person[2] or ssn} [{person[3].upper()}].")

    def _handle_feed(self, args):
        sub = args[0].lower()
        rest = args[1:]

        if sub == "list":
            feeds = self.feed_manager.list_feeds()
            self._print(f"Active feeds: {', '.join(str(f) for f in feeds)}" if feeds else "No active feeds.")
        elif sub == "add":
            if not rest:
                self._print("Usage: feed add [source]", ok=False)
                return
            source = int(rest[0]) if rest[0].isdigit() else rest[0]
            try:
                fid = self.feed_manager.add_feed(source)
                self._print(f"Feed {fid} added: {source}")
            except Exception as e:
                self._print(f"Failed to add feed: {e}", ok=False)
        elif sub == "remove":
            if not rest or not rest[0].isdigit():
                self._print("Usage: feed remove [feed ID]", ok=False)
                return
            self.feed_manager.remove_feed(int(rest[0]))
            self._print(f"Feed {rest[0]} removed.")
        elif sub == "focus":
            if not rest or not rest[0].isdigit():
                self._print("Usage: feed focus [feed ID]", ok=False)
                return
            fid = int(rest[0])
            self.feed_manager.focus_feed(fid)
            self._print(f"Focused feed {fid}.")
        elif sub == "grid":
            self.feed_manager.focus_feed(None)
            self._print("Returned to grid view.")
        else:
            self._print(f"Unknown feed command: '{sub}'", ok=False)

    def _handle_profiler(self, args):
        sub = args[0].lower()
        rest = args[1:]
        panel = self._main_window._profiler_panel

        if sub == "toggle":
            self._main_window.toggle_profiler()
            state = "open" if self._main_window._profiler_visible else "closed"
            self._print(f"Profiler panel {state}.")

        elif sub == "start":
            if not self._main_window._profiler_visible:
                self._main_window.toggle_profiler()
            panel.start()
            self._print("Profiler started — showing all detected faces.")

        elif sub == "stop":
            panel.stop()
            self._print("Profiler stopped.")

        elif sub == "show":
            if not rest:
                self._print("Usage: profiler show <SSN>", ok=False)
                return
            ssn = rest[0]
            if not self.db.get_by_ssn(ssn):
                self._print(f"No person found: {ssn}", ok=False)
                return
            if not self._main_window._profiler_visible:
                self._main_window.toggle_profiler()
            panel.show_single(ssn)
            self._print(f"Showing profile: {ssn}")

        elif sub == "enroll":
            if not rest:
                self._print("Usage: profiler enroll <imagename>", ok=False)
                return
            path = os.path.join(IMAGES_DIR, rest[0])
            if not os.path.exists(path):
                self._print(f"Image not found: {path}", ok=False)
                return
            ssn, success, error = self.db.enroll_from_image(
                self.feed_manager.app, path, designation='irrelevant'
            )
            if success:
                os.remove(path)
                self._print(f"Enrolled → {ssn}. Enter name (or 'skip'):")
                self._awaiting_name_for_ssn = ssn
                self._prompt_label.setText("name >")
            else:
                self._print(f"Enrollment failed: {error}", ok=False)

        elif sub == "remove":
            if not self._is_root():
                self._print("Access denied — root authentication required.", ok=False)
                return
            if not rest:
                self._print("Usage: profiler remove <SSN>", ok=False)
                return
            ssn = rest[0]
            if ssn == '000-00-0000':
                self._print("Cannot remove root user.", ok=False)
                return
            self._print(f"Removed {ssn}." if self.db.remove_person(ssn) else f"No person found: {ssn}", ok=self.db.get_by_ssn(ssn) is None)

        elif sub == "list":
            persons = self.db.get_all()
            if not persons:
                self._print("No persons on record.")
                return
            self._print(f"{len(persons)} person(s) on record:")
            for p in persons:
                _, ssn, name, designation, _, last_ts, _ = p
                self._print(f"  {ssn}  {(name or 'UNKNOWN'):<20}  {designation.upper():<12}  {last_ts or 'never'}")

        elif sub == "info":
            if not rest:
                self._print("Usage: profiler info <SSN>", ok=False)
                return
            person = self.db.get_by_ssn(rest[0])
            if not person:
                self._print(f"No person found: {rest[0]}", ok=False)
                return
            _, ssn, name, designation, notes, last_ts, last_feed = person
            self._print(f"ID:          {ssn}")
            self._print(f"Name:        {name or 'UNKNOWN'}")
            self._print(f"Designation: {designation.upper()}")
            self._print(f"Notes:       {notes or '—'}")
            self._print(f"Last seen:   {last_ts or 'never'} (feed {last_feed})")

        elif sub == "update":
            if len(rest) < 3:
                self._print("Usage: profiler update <SSN> <name|designation|notes> <value>", ok=False)
                return
            ssn, field, value = rest[0], rest[1].lower(), ' '.join(rest[2:])
            if field == 'designation':
                if not self._is_root():
                    self._print("Only root can change designations.", ok=False)
                    return
                if value not in DESIGNATIONS:
                    self._print(f"Invalid designation. Options: {', '.join(DESIGNATIONS)}", ok=False)
                    return
            self._print(f"Updated {field} for {ssn}." if self.db.update_person(ssn, field, value) else f"Update failed for {ssn}.", ok=True)

        else:
            self._print(f"Unknown profiler command: '{sub}'", ok=False)


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QWidget):
    def __init__(self, feed_manager, db, antispoof=None):
        super().__init__()
        self.feed_manager = feed_manager
        self.db = db
        self._antispoof = antispoof
        self._is_fullscreen = False
        self._profiler_visible = False

        self._init_ui()

        self._feed_timer = QTimer()
        self._feed_timer.timeout.connect(self._refresh_feed)
        self._feed_timer.start(33)

    def _init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet("background-color: #000000;")

        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setLayout(root_layout)

        self._title_bar = TitleBar(self)
        root_layout.addWidget(self._title_bar)

        self._middle = QWidget()
        self._middle_layout = QHBoxLayout()
        self._middle_layout.setContentsMargins(0, 0, 0, 0)
        self._middle_layout.setSpacing(0)
        self._middle.setLayout(self._middle_layout)

        self._feed_display = FeedDisplay()
        self._feed_display.setFixedHeight(FEED_H)
        self._middle_layout.addWidget(self._feed_display)

        self._profiler_panel = ProfilerPanel(self.feed_manager, self.db)
        self._profiler_panel.setVisible(False)
        self._middle_layout.addWidget(self._profiler_panel)

        root_layout.addWidget(self._middle)

        self._console = ConsoleWidget(feed_manager=self.feed_manager, db=self.db, main_window=self, antispoof=self._antispoof)
        root_layout.addWidget(self._console)

        # Give console input focus on startup
        self._console.focus_input()

    def toggle_profiler(self):
        self._profiler_visible = not self._profiler_visible
        self._profiler_panel.setVisible(self._profiler_visible)
        new_w = WINDOW_W + (PANEL_W if self._profiler_visible else 0)
        self.setFixedSize(new_w, WINDOW_H)

    def toggle_fullscreen(self):
        if self._is_fullscreen:
            self.setWindowFlags(Qt.FramelessWindowHint)
            new_w = WINDOW_W + (PANEL_W if self._profiler_visible else 0)
            self.setFixedSize(new_w, WINDOW_H)
            self._title_bar.setVisible(True)
            self.showNormal()
            self._is_fullscreen = False
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setFixedSize(self.screen().size().width(), self.screen().size().height())
            self._title_bar.setVisible(False)
            self.showFullScreen()
            self._is_fullscreen = True

    def _refresh_feed(self):
        frames = self.feed_manager.get_frames()
        if not frames:
            self._feed_display.show_placeholder()
            return
        focused_id = self.feed_manager.get_focused()
        if focused_id is not None and focused_id in frames and frames[focused_id] is not None:
            self._feed_display.update_frame(frames[focused_id].copy())
        else:
            self._feed_display.update_frame(self._render_grid(frames))

    def _render_grid(self, frames):
        W = self._feed_display.width()
        H = self._feed_display.height()
        if W == 0 or H == 0:
            return np.zeros((FEED_H, WINDOW_W, 3), dtype=np.uint8)

        feed_ids = list(frames.keys())
        count = len(feed_ids)

        if count == 1:
            fid = feed_ids[0]
            frame = frames[fid]
            if frame is None:
                blank = np.zeros((H, W, 3), dtype=np.uint8)
                cv2.putText(blank, f"FEED {fid} — WAITING", (10, H // 2),
                            cv2.FONT_HERSHEY_COMPLEX, 0.5, (100, 100, 100), 1)
                return blank
            cell = frame.copy()
            cv2.putText(cell, f"FEED {fid}", (8, 22),
                        cv2.FONT_HERSHEY_COMPLEX, 0.55, (255, 255, 255), 1)
            return cell

        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)
        cw, ch = W // cols, H // rows
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
        self._feed_timer.stop()
        self.feed_manager.stop()
        event.accept()