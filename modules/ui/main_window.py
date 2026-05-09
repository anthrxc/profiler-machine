# modules/ui/main_window.py
# Main application window with docked console and profiler panel.

import cv2
import math
import time
import os
import random
import threading
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QScrollArea, QLineEdit, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QImage, QPixmap, QColor, QPainter

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

        status_layout.addWidget(self._make_sep())

        self._status_track = QLabel("")
        self._status_track.setFont(QFont("Courier New", 8))
        self._status_track.setStyleSheet("color: #555555;")
        status_layout.addWidget(self._status_track)

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

        # Tracking status label
        tracked_ssn = self.feed_manager._designator.get_tracked_ssn()
        if tracked_ssn:
            if self.feed_manager._designator.is_tracked_visible():
                last_feed = self.feed_manager._designator.get_tracked_last_feed()
                feed_tag = f" FEED {last_feed}" if last_feed is not None else ""
                self._status_track.setText(f"TRACKING: {tracked_ssn}{feed_tag}")
                self._status_track.setStyleSheet("color: #ffa500;")
            else:
                self._status_track.setText(f"TRACKING: {tracked_ssn} [LOST]")
                self._status_track.setStyleSheet("color: #ff4444;")
        else:
            self._status_track.setText("")
            self._status_track.setStyleSheet("color: #555555;")

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
            self._print("alert [add/remove/list/mute/unmute]  —  add: designation|co-presence|ssn")
            self._print("profiler [toggle/start/stop/show/enroll/remove/update/list/info]")
            self._print("track <SSN>  |  untrack")

        elif primary == "fullscreen":
            self._main_window.toggle_fullscreen()
            self._print("Toggled fullscreen.")

        elif primary == "using":
            self._handle_using(args)

        elif primary == "track":
            if not args:
                self._print("Usage: track <SSN>", ok=False)
                return
            ssn = args[0]
            person = self.db.get_by_ssn(ssn)
            if not person:
                self._print(f"No person found: {ssn}", ok=False)
                return
            self.feed_manager._designator.set_tracked_ssn(ssn)
            name = person[2] or ssn
            self._print(f"Now tracking {name} [{ssn}] across all feeds.")

        elif primary == "untrack":
            current = self.feed_manager._designator.get_tracked_ssn()
            self.feed_manager._designator.clear_tracked_ssn()
            if current:
                self._print(f"Tracking cleared for {current}.")
            else:
                self._print("No active tracking target.")

        elif primary == "overlay":
            if not args:
                self._print(f"Roles: {', '.join(DESIGNATIONS)}", ok=False)
                return
            success = self.feed_manager._designator.set_debug_role(args[0].lower())
            self._print(f"Debug overlay: {args[0]}" if success else f"Unknown role: '{args[0]}'", ok=success)

        elif primary == "alert":
            if not args:
                self._print("Usage: alert [add/remove/list/mute/unmute]", ok=False)
                return
            self._handle_alert(args)

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
                # _latest_results is now {feed_id: [results]} — flatten all feeds
                all_results = []
                for feed_results in designator._latest_results.values():
                    all_results.extend(feed_results)
            # Find the bbox for this SSN
            bbox = None
            for r in all_results:
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

    def _handle_alert(self, args):
        from modules.profiler.alerts import parse_condition, ALERT_SOUND_PATH
        engine = self.feed_manager._alert_engine
        sub    = args[0].lower()
        rest   = args[1:]

        if sub == "add":
            if not rest:
                self._print(
                    "Usage: alert add <designation <role>> | "
                    "<co-presence <role_a> <role_b>> | <ssn <SSN>>",
                    ok=False
                )
                return
            try:
                cond = parse_condition(rest)
                created_by = getattr(self, '_active_user_ssn', None)
                rule = engine.add_rule(cond, created_by=created_by)
                self._print(
                    f"Alert rule {rule.rule_id} added: {rule.condition.describe()}"
                )
            except ValueError as e:
                self._print(str(e), ok=False)

        elif sub == "remove":
            if not rest or not rest[0].isdigit():
                self._print("Usage: alert remove <rule ID>", ok=False)
                return
            rid = int(rest[0])
            if engine.remove_rule(rid):
                self._print(f"Alert rule {rid} removed.")
            else:
                self._print(f"No alert rule with ID {rid}.", ok=False)

        elif sub == "list":
            rules = engine.list_rules()
            if not rules:
                self._print("No alert rules defined.")
                return
            self._print(f"{len(rules)} rule(s):")
            for r in rules:
                mute_tag = "  [MUTED]" if r.muted else ""
                self._print(
                    f"  [{r.rule_id}]  {r.condition.describe()}{mute_tag}"
                )

        elif sub == "mute":
            if not rest:
                engine.mute_all()
                self._print("All alerts muted.")
                return
            if not rest[0].isdigit():
                self._print("Usage: alert mute [rule ID]", ok=False)
                return
            rid = int(rest[0])
            if engine.mute_rule(rid):
                self._print(f"Alert rule {rid} muted.")
            else:
                self._print(f"No alert rule with ID {rid}.", ok=False)

        elif sub == "unmute":
            if not rest:
                engine.unmute_all()
                self._print("All alerts unmuted.")
                return
            if not rest[0].isdigit():
                self._print("Usage: alert unmute [rule ID]", ok=False)
                return
            rid = int(rest[0])
            if engine.unmute_rule(rid):
                self._print(f"Alert rule {rid} unmuted.")
            else:
                self._print(f"No alert rule with ID {rid}.", ok=False)

        else:
            self._print(f"Unknown alert command: '{sub}'", ok=False)

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
# Alert window
# ─────────────────────────────────────────────────────────────────────────────

ALERT_CARD_W = 520
ALERT_CARD_H = 190
ALERT_CARD_GAP = 6
ALERT_MAX_VISIBLE_CARDS = 3
ALERT_DISPLAY_SECONDS = 5.0


class AlertCard(QWidget):
    """
    A single alert card rendered from assets/gui/infocards/alert.png.
    The text placement matches the mockups in assets/gui/infocards/examples/.
    """

    def __init__(self, alert, parent=None):
        super().__init__(parent)
        self._alert = alert
        self.setFixedSize(ALERT_CARD_W, ALERT_CARD_H)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._build_ui()

    def _make_label(self, text, x, y, w, h, *, bold=False, size=18):
        lbl = QLabel(text, self)
        lbl.setGeometry(x, y, w, h)
        lbl.setStyleSheet(
            "color: #000000; "
            "font-family: 'Courier New', monospace; "
            f"font-size: {size}px; "
            f"font-weight: {'bold' if bold else 'normal'}; "
            "background: transparent;"
        )
        lbl.setWordWrap(False)
        return lbl

    def _build_ui(self):
        alert = self._alert

        template_path = os.path.join('assets', 'gui', 'infocards', 'alert.png')
        bg = QLabel(self)
        bg.setGeometry(0, 0, ALERT_CARD_W, ALERT_CARD_H)
        if os.path.exists(template_path):
            bg.setPixmap(QPixmap(template_path))
            bg.setScaledContents(True)
        else:
            bg.setStyleSheet('background-color: #cc0000; border-top: 15px solid #000000;')

        title = QLabel(f"! ALERT ENGINE - RULE {alert.rule.rule_id} TRIGGERED", self)
        title.setGeometry(6, 0, ALERT_CARD_W - 12, 24)
        title.setStyleSheet(
            "color: #ff0000; font-family: 'Courier New', monospace; "
            "font-size: 17px; font-weight: bold; background: transparent;"
        )

        subjects = getattr(alert, 'subjects', []) or []
        is_copresence = len(subjects) >= 2

        if is_copresence:
            a_name, a_ssn, a_desig = subjects[0]
            b_name, b_ssn, b_desig = subjects[1]
            self._make_label(f"{a_name.upper()} ({a_ssn})  IN FEED {alert.feed_id}", 8, 32, ALERT_CARD_W - 16, 26, bold=True, size=20)
            self._make_label(f"DESIGNATION: {a_desig.upper()}", 8, 60, ALERT_CARD_W - 16, 24, size=18)
            self._make_label(f"{b_name.upper()} ({b_ssn})  IN FEED {alert.feed_id}", 8, 92, ALERT_CARD_W - 16, 26, bold=True, size=20)
            self._make_label(f"DESIGNATION: {b_desig.upper()}", 8, 120, ALERT_CARD_W - 16, 24, size=18)
        elif subjects:
            name, ssn, desig = subjects[0]
            self._make_label(f"{name.upper()} ({ssn})  IN FEED {alert.feed_id}", 8, 38, ALERT_CARD_W - 16, 30, bold=True, size=22)
            self._make_label(f"DESIGNATION: {desig.upper()}", 8, 76, ALERT_CARD_W - 16, 28, size=20)
        else:
            self._make_label(f"{getattr(alert, 'label', 'ALERT').upper()}  IN FEED {alert.feed_id}", 8, 38, ALERT_CARD_W - 16, 32, bold=True, size=22)

        alert_type = alert.rule.condition.describe().split(':', 1)[0].upper()
        created_by = getattr(alert, 'created_by_name', 'UNKNOWN')
        self._make_label(f"{alert_type} ALERT ADDED BY {str(created_by).upper()}", 8, 164, ALERT_CARD_W - 16, 22, bold=True, size=16)


class AlertWindow(QWidget):
    """
    Floating alert window beside the main app.
    Shows up to 3 cards without scrolling; 4+ active alerts become scrollable.
    """

    def __init__(self):
        super().__init__(None)
        self._entries = []  # [{'uid': int, 'alert': ActiveAlert, 'card': AlertCard, 'born_at': float}]
        self._seen_ids = set()
        self._anchor_x = 0
        self._anchor_y = 0

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(ALERT_CARD_W + 18)

        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._outer_layout.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical { background: #220000; width: 8px; }
            QScrollBar::handle:vertical { background: #880000; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(ALERT_CARD_GAP)
        self._scroll.setWidget(self._content)
        self._outer_layout.addWidget(self._scroll)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)

    def anchor_to(self, main_window):
        geo = main_window.frameGeometry()
        self._anchor_x = geo.right() + 8
        self._anchor_y = geo.top()
        self.move(self._anchor_x, self._anchor_y)

    def push_alerts(self, active_alerts: list):
        now = time.time()
        added = False

        for alert in active_alerts:
            uid = id(alert)
            if uid in self._seen_ids:
                continue

            self._seen_ids.add(uid)
            card = AlertCard(alert, self._content)
            self._content_layout.addWidget(card)
            self._entries.append({
                'uid': uid,
                'alert': alert,
                'card': card,
                'born_at': getattr(alert, 'born_at', now),
            })
            added = True

        if added:
            self._refresh_window()

    def _tick(self):
        now = time.time()
        kept = []

        for entry in self._entries:
            if now - entry['born_at'] >= ALERT_DISPLAY_SECONDS:
                entry['card'].setParent(None)
                entry['card'].deleteLater()
                self._seen_ids.discard(entry['uid'])
            else:
                kept.append(entry)

        if len(kept) != len(self._entries):
            self._entries = kept
            self._refresh_window()

    def _refresh_window(self):
        count = len(self._entries)
        if count <= 0:
            self.hide()
            return

        visible_count = min(count, ALERT_MAX_VISIBLE_CARDS)
        height = (visible_count * ALERT_CARD_H) + ((visible_count - 1) * ALERT_CARD_GAP)
        self.setFixedHeight(height)
        self._scroll.setFixedHeight(height)

        # 1-3 alerts: no scrollbar. 4+ alerts: scrolling list of active alerts.
        if count <= ALERT_MAX_VISIBLE_CARDS:
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        else:
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.move(self._anchor_x, self._anchor_y)
        self.show()
        self.raise_()

    def close(self):
        for entry in self._entries:
            entry['card'].close()
        self._entries.clear()
        self.hide()
        super().close()

# Main window
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Intro sequence
# ─────────────────────────────────────────────────────────────────────────────

_GLITCH_CHARS = "█▓▒░╔╗╚╝║═╠╣╦╩╬▲▼◄►◆○●□■"

def _fake_coord():
    lat  = f"{random.uniform(-90, 90):+.5f}"
    lon  = f"{random.uniform(-180, 180):+.5f}"
    return f"{lat} / {lon}"

def _fake_hex(n=16):
    return ' '.join(f'{random.randint(0,255):02X}' for _ in range(n))

def _fake_signal():
    return f"{random.randint(72, 99)}%"

def _glitch_line(length=60):
    return ''.join(random.choice(_GLITCH_CHARS) for _ in range(length))


class IntroLine:
    """One rendered row in the intro terminal."""
    def __init__(self, text, color, bold=False, indent=0):
        self.text   = text
        self.color  = color   # hex string
        self.bold   = bold
        self.indent = indent


class IntroSequence(QWidget):
    """
    Full-window terminal intro that plays over MainWindow on first launch.
    Three acts:
      Act 1 — feed uplink (one block per active camera)
      Act 2 — system scan readout
      Act 3 — operator identity confirm
    Emits `finished` when done so MainWindow can start its feed timer.
    """
    finished = pyqtSignal()

    # Timing knobs (milliseconds)
    _TICK           = 40    # base repaint interval
    _LINE_DELAY     = 55    # ms between lines appearing
    _GLITCH_FRAMES  = 6     # frames a glitch line stays before resolving
    _ACT_GAP        = 420   # pause between acts
    _HOLD_FINAL     = 1800  # hold "PROFILER MACHINE ONLINE" before fade
    _FADE_STEPS     = 20    # opacity steps for fade-out

    def __init__(self, parent, feed_manager, db):
        super().__init__(parent)
        self._feed_manager = feed_manager
        self._db           = db

        self._lines        = []          # list[IntroLine] — fully revealed lines
        self._pending      = []          # queue of (delay_ms, IntroLine)
        self._glitch_text  = None        # current glitch line or None
        self._glitch_ttl   = 0
        self._opacity      = 255
        self._fading       = False
        self._done         = False
        self._elapsed_debt = 0           # accumulates ms between scheduled lines

        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()

        # Build script in background so DB call doesn't block the UI thread
        threading.Thread(target=self._build_and_start, daemon=True).start()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(self._TICK)

    # ------------------------------------------------------------------ build

    def _build_and_start(self):
        """Build the full line script then hand it to the main thread via pending queue."""
        pending = []   # list of (cumulative_delay_ms, IntroLine)
        t = 0          # cursor in ms

        def line(text, color="#cccccc", bold=False, indent=0, delay=None):
            nonlocal t
            d = delay if delay is not None else self._LINE_DELAY
            t += d
            pending.append((t, IntroLine(text, color, bold, indent)))

        def blank(delay=80):
            line("", "#000000", delay=delay)

        # ── HEADER ──────────────────────────────────────────────────────────
        line("",        delay=0)
        line("╔" + "═"*66 + "╗", "#1a4a1a", delay=120)
        line("║  P R O F I L E R   M A C H I N E   //   S Y S T E M   B O O T    ║", "#22cc22", bold=True, delay=80)
        line("╚" + "═"*66 + "╝", "#1a4a1a", delay=80)
        blank(200)

        # ── ACT 1: FEED UPLINK ───────────────────────────────────────────────
        line("[ ACT I ]  ESTABLISHING UPLINKS", "#555555", delay=self._ACT_GAP)
        line("─"*68, "#1a3a1a", delay=60)
        blank(80)

        feed_ids = self._feed_manager.list_feeds()
        if not feed_ids:
            feed_ids = [0]

        for fid in feed_ids:
            tag = f"CAM-{fid:02d}"
            coord = _fake_coord()
            sig   = _fake_signal()

            line(f"  UPLINK  {tag}", "#888888", delay=180)
            # glitch sentinel — negative delay means "show glitch before this"
            t += 220
            pending.append((t, IntroLine("__GLITCH__", "#333333")))
            t += 260
            pending.append((t, IntroLine("__GLITCH__", "#333333")))
            line(f"  {tag}   COORDINATES  {coord}", "#446644", delay=200)
            line(f"  {tag}   SIGNAL       {sig}  ▉▉▉▉▉▉▉▉░░", "#446644", delay=80)
            line(f"  {tag}   ENCRYPTION   AES-256-GCM / ECDH-P384", "#446644", delay=80)
            line(f"  {tag}   STATUS       ██ ONLINE", "#22cc22", bold=True, delay=80)
            blank(120)

        # ── ACT 2: SYSTEM SCAN ───────────────────────────────────────────────
        line("[ ACT II ]  SYSTEM SCAN", "#555555", delay=self._ACT_GAP)
        line("─"*68, "#1a3a1a", delay=60)
        blank(80)

        person_count = 0
        try:
            person_count = self._db.count()
        except Exception:
            pass

        threat_count = 0
        try:
            all_persons = self._db.get_all()
            threat_count = sum(1 for p in all_persons if p[3] in ('threat', 'perpetrator'))
        except Exception:
            pass

        scan_lines = [
            ("PERSONS ON RECORD",    f"{person_count}",                         "#cccccc"),
            ("THREAT INDEX",         f"{threat_count} FLAGGED SUBJECT(S)",      "#ff6644" if threat_count else "#cccccc"),
            ("FACIAL MODEL",         "INSIGHTFACE  buffalo_l  [GPU]",            "#cccccc"),
            ("ANTI-SPOOF",           "MiniFASNetV2  ONNX  [ACTIVE]",             "#cccccc"),
            ("TRACKER",              "BYTETRACK  v0.3  [ACTIVE]",                "#cccccc"),
            ("UPLINK PROTOCOL",      "TLS 1.3 / SRTP",                           "#cccccc"),
            ("JURISDICTION",         "UNRESTRICTED",                             "#ff4444"),
            ("CLASSIFICATION",       "TS//SCI//PROFM",                           "#ff4444"),
            ("KERNEL",               _fake_hex(8),                               "#335533"),
            ("INTEGRITY HASH",       _fake_hex(12),                              "#335533"),
        ]

        max_key = max(len(k) for k, _, _ in scan_lines)
        for key, val, col in scan_lines:
            dots = "." * (max_key - len(key) + 4)
            line(f"  {key}{dots}{val}", col, delay=self._LINE_DELAY + random.randint(0, 40))

        blank(100)
        line("  ALL SUBSYSTEMS  ██ NOMINAL", "#22cc22", bold=True, delay=180)
        blank(80)

        # ── ACT 3: OPERATOR IDENTITY ─────────────────────────────────────────
        line("[ ACT III ]  OPERATOR AUTHENTICATION", "#555555", delay=self._ACT_GAP)
        line("─"*68, "#1a3a1a", delay=60)
        blank(80)

        operator_name  = "UNIDENTIFIED"
        operator_level = "GUEST"
        operator_ssn   = "???-??-????"
        try:
            all_p = self._db.get_all()
            roots = [p for p in all_p if p[3] == 'root']
            if roots:
                p = roots[0]
                operator_ssn   = p[1]
                operator_name  = (p[2] or "UNKNOWN").upper()
                operator_level = "ROOT"
            else:
                admins = [p for p in all_p if p[3] == 'admin']
                if admins:
                    p = admins[0]
                    operator_ssn   = p[1]
                    operator_name  = (p[2] or "UNKNOWN").upper()
                    operator_level = "ADMIN"
        except Exception:
            pass

        id_col = "#22cc22" if operator_level in ("ROOT", "ADMIN") else "#888888"

        line(f"  OPERATOR ID ........ {operator_ssn}",   id_col, delay=220)
        line(f"  OPERATOR NAME ...... {operator_name}",  id_col, delay=160, bold=True)
        line(f"  CLEARANCE .......... {operator_level}", id_col, delay=160)
        blank(120)

        if operator_level == "ROOT":
            line("  ██ FULL SYSTEM ACCESS GRANTED", "#22cc22", bold=True, delay=220)
        elif operator_level == "ADMIN":
            line("  ██ ELEVATED ACCESS GRANTED", "#22cc22", bold=True, delay=220)
        else:
            line("  ░░ LIMITED ACCESS — AUTHENTICATE TO CONTINUE", "#888888", delay=220)

        blank(200)

        # ── FINAL BANNER ─────────────────────────────────────────────────────
        line("╔" + "═"*66 + "╗", "#1a4a1a", delay=self._ACT_GAP)
        line("║" + " "*18 + "P R O F I L E R   M A C H I N E" + " "*17 + "║", "#22cc22", bold=True, delay=100)
        line("║" + " "*26 + "O N L I N E" + " "*29 + "║",                      "#22cc22", bold=True, delay=100)
        line("╚" + "═"*66 + "╝", "#1a4a1a", delay=100)

        # sentinel: start fade after hold
        t += self._HOLD_FINAL
        pending.append((t, IntroLine("__FADE__", "#000000")))

        self._pending = pending

    # ------------------------------------------------------------------ tick

    def _tick(self):
        if self._done:
            return

        if self._fading:
            self._opacity = max(0, self._opacity - (255 // self._FADE_STEPS))
            self.update()
            if self._opacity == 0:
                self._tick_timer.stop()
                self._done = True
                self.hide()
                self.finished.emit()
            return

        self._elapsed_debt += self._TICK

        # Drain any pending lines whose time has come
        while self._pending and self._pending[0][0] <= self._elapsed_debt:
            _, intro_line = self._pending.pop(0)

            if intro_line.text == "__GLITCH__":
                self._glitch_text = _glitch_line()
                self._glitch_ttl  = self._GLITCH_FRAMES
            elif intro_line.text == "__FADE__":
                self._fading = True
                break
            else:
                self._lines.append(intro_line)

        # Age glitch
        if self._glitch_ttl > 0:
            self._glitch_ttl -= 1
            if self._glitch_ttl == 0:
                self._glitch_text = None

        self.update()

    # ------------------------------------------------------------------ paint

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setOpacity(self._opacity / 255.0)

        # Background
        painter.fillRect(self.rect(), QColor(0, 0, 0))

        font_normal = QFont("Courier New", 10)
        font_bold   = QFont("Courier New", 10)
        font_bold.setBold(True)

        fm      = painter.fontMetrics()
        line_h  = fm.height() + 3
        margin  = 60
        y_start = 44

        # How many lines fit on screen
        visible_h  = self.height() - y_start - 20
        max_lines  = visible_h // line_h

        # Show only the last max_lines lines (scroll effect)
        visible = self._lines[-max_lines:] if len(self._lines) > max_lines else self._lines

        y = y_start
        for il in visible:
            painter.setFont(font_bold if il.bold else font_normal)
            painter.setPen(QColor(il.color))
            painter.drawText(margin + il.indent, y, il.text)
            y += line_h

        # Glitch line at cursor position
        if self._glitch_text:
            painter.setFont(font_normal)
            painter.setPen(QColor("#1a3a1a"))
            painter.drawText(margin, y, self._glitch_text)

        painter.end()

    def resizeEvent(self, event):
        self.setGeometry(self.parent().rect())
        super().resizeEvent(event)


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

        # Give the alert engine a console callback now that the console exists
        self.feed_manager.set_console(self._console._print)

        # Floating alert window
        self._alert_window = AlertWindow()

        # Intro plays first — feed timer starts only after it finishes
        self._intro = IntroSequence(self, feed_manager, db)
        self._intro.finished.connect(self._on_intro_finished)

        self._feed_timer = QTimer()
        self._feed_timer.timeout.connect(self._refresh_feed)
        # Feed timer is NOT started here — _on_intro_finished starts it

        # Cross-feed tracking lost/reacquired monitor
        self._track_was_visible = False
        self._track_monitor = QTimer()
        self._track_monitor.timeout.connect(self._check_tracking)

    def _on_intro_finished(self):
        self._feed_timer.start(33)
        self._track_monitor.start(1000)

    def _check_tracking(self):
        """Fire console messages and audio when tracked subject is lost or reacquired."""
        designator = self.feed_manager._designator
        tracked_ssn = designator.get_tracked_ssn()
        if not tracked_ssn:
            self._track_was_visible = False
            return

        now_visible = designator.is_tracked_visible()
        if self._track_was_visible and not now_visible:
            last_feed = designator.get_tracked_last_feed()
            feed_tag = f" — last seen in FEED {last_feed}" if last_feed is not None else ""
            self._console._print(f"SUBJECT LOST: {tracked_ssn}{feed_tag}", ok=False)
            threading.Thread(target=self._play_alert, daemon=True).start()
        elif not self._track_was_visible and now_visible:
            last_feed = designator.get_tracked_last_feed()
            feed_tag = f" — reacquired in FEED {last_feed}" if last_feed is not None else ""
            self._console._print(f"SUBJECT REACQUIRED: {tracked_ssn}{feed_tag}")
            threading.Thread(target=self._play_alert, daemon=True).start()

        self._track_was_visible = now_visible

    def _play_alert(self):
        try:
            from modules.io.playsound import play_sound
            play_sound(os.path.join('assets', 'audio', 'alert.wav'))
        except Exception:
            pass

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
        # Drain alert console messages queued from the background thread
        self.feed_manager._alert_engine.flush_console_queue()

        # Push all active alerts to the floating alert window
        all_alerts = []
        for fid in self.feed_manager.list_feeds():
            all_alerts.extend(
                self.feed_manager._alert_engine.get_active_alerts(fid)
            )
        if all_alerts:
            self._alert_window.anchor_to(self)
            self._alert_window.push_alerts(all_alerts)

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

        # Cross-feed tracking: highlight last-known feed when subject is lost
        designator = self.feed_manager._designator
        tracked_ssn       = designator.get_tracked_ssn()
        tracked_visible   = designator.is_tracked_visible() if tracked_ssn else False
        tracked_last_feed = designator.get_tracked_last_feed() if tracked_ssn else None
        # Show amber border on last-known feed only while subject is LOST
        highlight_fid = tracked_last_feed if (tracked_ssn and not tracked_visible and tracked_last_feed is not None) else None

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
            if fid == highlight_fid:
                cv2.rectangle(cell, (0, 0), (W - 1, H - 1), (0, 165, 255), 2)
                cv2.putText(cell, "LAST KNOWN LOCATION", (8, H - 10),
                            cv2.FONT_HERSHEY_COMPLEX_SMALL, 0.6, (0, 165, 255), 1)
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
                cell = self._letterbox(frame, cw, ch)
                cv2.putText(cell, f"FEED {fid}", (8, 22),
                            cv2.FONT_HERSHEY_COMPLEX, 0.55, (255, 255, 255), 1)
                if fid == highlight_fid:
                    cv2.rectangle(cell, (0, 0), (cw - 1, ch - 1), (0, 165, 255), 2)
                    cv2.putText(cell, "LAST KNOWN", (4, ch - 6),
                                cv2.FONT_HERSHEY_COMPLEX_SMALL, 0.5, (0, 165, 255), 1)
                else:
                    cv2.rectangle(cell, (0, 0), (cw - 1, ch - 1), (40, 40, 40), 1)
            grid[y:y + ch, x:x + cw] = cell

        return grid

    @staticmethod
    def _letterbox(frame, target_w, target_h):
        """Fit frame into (target_w × target_h) preserving aspect ratio, padding with black."""
        fh, fw = frame.shape[:2]
        scale = min(target_w / fw, target_h / fh)
        new_w, new_h = int(fw * scale), int(fh * scale)
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        cell = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        pad_x = (target_w - new_w) // 2
        pad_y = (target_h - new_h) // 2
        cell[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
        return cell

    def moveEvent(self, event):
        self._alert_window.anchor_to(self)
        super().moveEvent(event)

    def closeEvent(self, event):
        self._alert_window.close()
        self._feed_timer.stop()
        self.feed_manager.stop()
        event.accept()