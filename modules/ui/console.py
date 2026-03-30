# modules/ui/console.py
# Floating command console window with terminal aesthetic.

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence

WINDOW_W, WINDOW_H = 600, 120
TITLE_BAR_H = 28


class Console(QWidget):
    # Signal emitted when a command is submitted
    command_submitted = pyqtSignal(str)

    def __init__(self, main_window, feed_manager):
        super().__init__()
        self.main_window = main_window
        self.feed_manager = feed_manager
        self._drag_pos = None

        self._init_ui()
        self.hide()

    def _init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet("background-color: #000000;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(TITLE_BAR_H)
        title_bar.setStyleSheet("background-color: #111111;")
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release

        tb_layout = QHBoxLayout()
        tb_layout.setContentsMargins(10, 0, 10, 0)
        title_bar.setLayout(tb_layout)

        title = QLabel("PROFILER MACHINE // CONSOLE")
        title.setFont(QFont("Courier New", 9))
        title.setStyleSheet("color: #aaaaaa;")
        tb_layout.addWidget(title)

        tb_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFont(QFont("Courier New", 9))
        btn_close.setFixedSize(28, 20)
        btn_close.setStyleSheet("""
            QPushButton { background-color: #1a1a1a; color: #aaaaaa; border: none; }
            QPushButton:hover { background-color: #cc0000; color: #ffffff; }
        """)
        btn_close.clicked.connect(self.hide)
        tb_layout.addWidget(btn_close)

        layout.addWidget(title_bar)

        # Status line
        self._status = QLabel("")
        self._status.setFont(QFont("Courier New", 9))
        self._status.setStyleSheet("color: #aaaaaa; padding: 4px 12px 0px 12px;")
        layout.addWidget(self._status)

        # Input row
        input_row = QWidget()
        input_row.setStyleSheet("background-color: #000000;")
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(12, 6, 12, 12)
        input_layout.setSpacing(6)
        input_row.setLayout(input_layout)

        prompt = QLabel(">")
        prompt.setFont(QFont("Courier New", 11))
        prompt.setStyleSheet("color: #ffffff;")
        input_layout.addWidget(prompt)

        self._input = QLineEdit()
        self._input.setFont(QFont("Courier New", 11))
        self._input.setStyleSheet("""
            QLineEdit {
                background-color: #000000;
                color: #ffffff;
                border: none;
                selection-background-color: #333333;
            }
        """)
        self._input.returnPressed.connect(self._on_submit)
        input_layout.addWidget(self._input)

        layout.addWidget(input_row)

    # -------------------------------------------------------------------------
    # Dragging
    # -------------------------------------------------------------------------

    def _title_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPos() - self._drag_pos)

    def _title_mouse_release(self, event):
        self._drag_pos = None

    # -------------------------------------------------------------------------
    # Visibility
    # -------------------------------------------------------------------------

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self._input.setFocus()

    # -------------------------------------------------------------------------
    # Command handling
    # -------------------------------------------------------------------------

    def _set_status(self, message, ok=True):
        color = "#aaaaaa" if ok else "#ff4444"
        self._status.setStyleSheet(f"color: {color}; padding: 4px 12px 0px 12px;")
        self._status.setText(message)

    def _on_submit(self):
        cmd = self._input.text().strip()
        self._input.clear()
        if not cmd:
            return
        self._handle_command(cmd)

    def _handle_command(self, cmd):
        parts = cmd.strip().split()
        primary = parts[0].lower()
        args = parts[1:]

        if primary == "quit":
            self._set_status("SHUTTING DOWN...")
            self.main_window.close()

        elif primary == "help" or primary == "?":
            self._set_status("quit | fullscreen | feed [add/remove/focus/grid/list]")

        elif primary == "fullscreen":
            self.main_window.toggle_fullscreen()
            self._set_status("Toggled fullscreen.")

        elif primary == "feed":
            if not args:
                self._set_status("Usage: feed [add/remove/focus/grid/list]", ok=False)
                return
            self._handle_feed(args)

        else:
            self._set_status(f"Unknown command: '{primary}'", ok=False)

    def _handle_feed(self, args):
        sub = args[0].lower()
        rest = args[1:]

        if sub == "list":
            feeds = self.feed_manager.list_feeds()
            if feeds:
                self._set_status(f"Active feeds: {', '.join(str(f) for f in feeds)}")
            else:
                self._set_status("No active feeds.")

        elif sub == "add":
            if not rest:
                self._set_status("Usage: feed add [source]", ok=False)
                return
            source = rest[0]
            if source.isdigit():
                source = int(source)
            try:
                fid = self.feed_manager.add_feed(source)
                self._set_status(f"Feed {fid} added: {source}")
            except Exception as e:
                self._set_status(f"Failed to add feed: {e}", ok=False)

        elif sub == "remove":
            if not rest or not rest[0].isdigit():
                self._set_status("Usage: feed remove [feed ID]", ok=False)
                return
            fid = int(rest[0])
            self.feed_manager.remove_feed(fid)
            self._set_status(f"Feed {fid} removed.")

        elif sub == "focus":
            if not rest or not rest[0].isdigit():
                self._set_status("Usage: feed focus [feed ID]", ok=False)
                return
            fid = int(rest[0])
            self.feed_manager.focus_feed(fid)
            self._set_status(f"Focused feed {fid}.")

        elif sub == "grid":
            self.feed_manager.focus_feed(None)
            self._set_status("Returned to grid view.")

        else:
            self._set_status(f"Unknown feed command: '{sub}'", ok=False)