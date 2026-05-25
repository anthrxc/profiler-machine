# modules/ui/log_viewer.py
# Floating terminal-aesthetic log viewer.
# Open with: logs

import os
import time

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QComboBox, QFileDialog, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from modules.core.logger import get_logger, LEVELS, MODULES

VIEWER_W    = 980
VIEWER_H    = 560
TITLE_BAR_H = 32
MAX_DISPLAY = 1000   # cap rows in view to avoid widget overload

LEVEL_COLORS = {
    'debug':   '#555555',
    'info':    '#aaaaaa',
    'warning': '#ffaa44',
    'error':   '#ff4444',
}

TIME_PRESETS = [
    ('ALL',  0),
    ('1H',   3600),
    ('15M',  900),
    ('5M',   300),
]


class LogViewerWindow(QWidget):

    def __init__(self, parent=None):
        super().__init__(None)  # free-floating top-level window
        self._logger        = get_logger()
        self._filter_level  = 'all'
        self._filter_module = 'all'
        self._filter_since  = 0.0
        self._drag_pos      = None
        self._last_count    = -1
        self._dirty         = True   # force first build
        self._time_btns     = {}

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setFixedSize(VIEWER_W, VIEWER_H)
        self.setStyleSheet("background-color: #0a0a0a;")
        self._init_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)

    # ─────────────────────────────────────────────────────────────────── UI build

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_filter_bar())
        root.addWidget(self._build_column_header())
        root.addWidget(self._build_log_area(), 1)
        root.addWidget(self._build_status_bar())

    def _build_title_bar(self):
        bar = QWidget()
        bar.setFixedHeight(TITLE_BAR_H)
        bar.setStyleSheet("background-color: #111111;")
        bar.mousePressEvent   = self._tb_press
        bar.mouseMoveEvent    = self._tb_move
        bar.mouseReleaseEvent = lambda _e: setattr(self, '_drag_pos', None)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        title = QLabel("PROFILER MACHINE  //  SYSTEM LOG")
        title.setFont(QFont("Courier New", 10))
        title.setStyleSheet("color: #ffffff;")
        layout.addWidget(title)
        layout.addStretch()

        btn = QPushButton("✕")
        btn.setFont(QFont("Courier New", 9))
        btn.setFixedSize(36, 22)
        btn.setStyleSheet("""
            QPushButton { background-color: #1a1a1a; color: #aaaaaa; border: none; }
            QPushButton:hover { background-color: #cc0000; color: #ffffff; }
        """)
        btn.clicked.connect(self.hide)
        layout.addWidget(btn)
        return bar

    def _build_filter_bar(self):
        bar = QWidget()
        bar.setFixedHeight(38)
        bar.setStyleSheet("background-color: #111111; border-bottom: 1px solid #1e1e1e;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(12)

        # Level
        layout.addWidget(self._dim_label("LEVEL"))
        self._level_combo = self._make_combo(['ALL'] + [l.upper() for l in LEVELS])
        self._level_combo.currentTextChanged.connect(
            lambda t: self._set_filter(level=t.lower()))
        layout.addWidget(self._level_combo)

        # Module
        layout.addWidget(self._dim_label("MODULE"))
        self._module_combo = self._make_combo(['ALL'] + [m.upper() for m in MODULES])
        self._module_combo.currentTextChanged.connect(
            lambda t: self._set_filter(module=t.lower()))
        layout.addWidget(self._module_combo)

        # Time presets
        layout.addWidget(self._dim_label("TIME"))
        for label, secs in TIME_PRESETS:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 8))
            btn.setFixedHeight(22)
            btn.setStyleSheet(self._time_btn_css(active=(secs == 0)))
            btn.clicked.connect(lambda _chk, s=secs: self._set_time(s))
            self._time_btns[secs] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Entry count
        self._count_lbl = QLabel("—")
        self._count_lbl.setFont(QFont("Courier New", 8))
        self._count_lbl.setStyleSheet("color: #555555;")
        layout.addWidget(self._count_lbl)

        layout.addWidget(self._vsep())

        # Export
        export_btn = QPushButton("EXPORT")
        export_btn.setFont(QFont("Courier New", 8))
        export_btn.setFixedHeight(22)
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #0d1a0d; color: #44aa44;
                border: 1px solid #1a3a1a; padding: 0 8px;
            }
            QPushButton:hover { background-color: #122212; color: #66cc66; }
        """)
        export_btn.clicked.connect(self._export)
        layout.addWidget(export_btn)

        return bar

    def _build_column_header(self):
        hdr = QWidget()
        hdr.setFixedHeight(20)
        hdr.setStyleSheet("background-color: #0d0d0d; border-bottom: 1px solid #1a1a1a;")
        layout = QHBoxLayout(hdr)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(0)
        for text, fixed_w in [("TIME", 68), ("LEVEL", 80), ("MODULE", 108), ("MESSAGE", None)]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Courier New", 8))
            lbl.setStyleSheet("color: #333333;")
            if fixed_w:
                lbl.setFixedWidth(fixed_w)
            else:
                lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            layout.addWidget(lbl)
        return hdr

    def _build_log_area(self):
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: #0a0a0a; }
            QScrollBar:vertical { background: #0f0f0f; width: 6px; }
            QScrollBar::handle:vertical { background: #2a2a2a; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        self._log_container = QWidget()
        self._log_container.setStyleSheet("background-color: #0a0a0a;")
        self._log_layout = QVBoxLayout(self._log_container)
        self._log_layout.setContentsMargins(0, 2, 0, 2)
        self._log_layout.setSpacing(0)
        self._log_layout.addStretch()
        self._scroll.setWidget(self._log_container)
        return self._scroll

    def _build_status_bar(self):
        bar = QWidget()
        bar.setFixedHeight(22)
        bar.setStyleSheet("background-color: #0d0d0d; border-top: 1px solid #1a1a1a;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        self._status_lbl = QLabel("Monitoring…")
        self._status_lbl.setFont(QFont("Courier New", 8))
        self._status_lbl.setStyleSheet("color: #333333;")
        layout.addWidget(self._status_lbl)
        layout.addStretch()
        return bar

    # ─────────────────────────────────────────────────────────────────── helpers

    def _dim_label(self, text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet("color: #555555;")
        return lbl

    def _make_combo(self, options):
        cb = QComboBox()
        cb.setFont(QFont("Courier New", 8))
        cb.setFixedHeight(22)
        cb.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a; color: #888888;
                border: 1px solid #2a2a2a; padding: 0 6px;
            }
            QComboBox::drop-down { border: none; width: 16px; }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a; color: #aaaaaa;
                selection-background-color: #2a2a2a;
            }
        """)
        for opt in options:
            cb.addItem(opt)
        return cb

    def _vsep(self):
        sep = QLabel("  |  ")
        sep.setFont(QFont("Courier New", 8))
        sep.setStyleSheet("color: #222222;")
        return sep

    def _time_btn_css(self, active=False):
        if active:
            return """QPushButton {
                background-color: #1a2a1a; color: #44aa44;
                border: 1px solid #2a4a2a; padding: 0 8px;
            }"""
        return """QPushButton {
            background-color: #141414; color: #444444;
            border: 1px solid #1e1e1e; padding: 0 8px;
        }
        QPushButton:hover { color: #888888; background-color: #1a1a1a; }"""

    # ─────────────────────────────────────────────────────────────────── drag

    def _tb_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def _tb_move(self, e):
        if e.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(e.globalPos() - self._drag_pos)

    # ─────────────────────────────────────────────────────────────────── filters

    def _set_filter(self, level=None, module=None):
        if level  is not None: self._filter_level  = level
        if module is not None: self._filter_module = module
        self._dirty = True

    def _set_time(self, secs):
        self._filter_since = time.time() - secs if secs > 0 else 0.0
        for s, btn in self._time_btns.items():
            btn.setStyleSheet(self._time_btn_css(active=(s == secs)))
        self._dirty = True

    def _get_filtered(self):
        return self._logger.get_entries(
            level    = None if self._filter_level  == 'all' else self._filter_level,
            module   = None if self._filter_module == 'all' else self._filter_module,
            since_ts = self._filter_since if self._filter_since > 0 else None,
        )

    # ─────────────────────────────────────────────────────────────────── tick

    def _tick(self):
        if not self.isVisible():
            return

        entries = self._get_filtered()
        new_count = len(entries)

        # Update module combo with newly seen modules
        known = self._logger.get_known_modules()
        current_items = [self._module_combo.itemText(i).lower()
                         for i in range(self._module_combo.count())]
        for mod in known:
            if mod not in current_items:
                self._module_combo.addItem(mod.upper())

        if self._dirty or new_count != self._last_count:
            self._rebuild(entries)
            self._dirty = False

    # ─────────────────────────────────────────────────────────────────── rebuild

    def _rebuild(self, entries):
        # Clear all rows (keep trailing stretch)
        while self._log_layout.count() > 1:
            item = self._log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        display = entries[-MAX_DISPLAY:]
        truncated = len(entries) - len(display)

        if truncated > 0:
            note = QLabel(f"  ↑ {truncated} older entries hidden — narrow filters or use EXPORT for full log")
            note.setFont(QFont("Courier New", 8))
            note.setStyleSheet("color: #444444; padding: 2px 0;")
            self._log_layout.insertWidget(0, note)

        for entry in display:
            self._log_layout.insertWidget(self._log_layout.count() - 1,
                                          self._make_row(entry))

        total = len(self._logger.get_entries())
        self._last_count = len(entries)
        self._count_lbl.setText(f"{len(entries)} shown / {total} total")
        self._status_lbl.setText(f"Updated {time.strftime('%H:%M:%S')}")

        QTimer.singleShot(40, lambda:
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            )
        )

    def _make_row(self, entry):
        row = QWidget()
        row.setFixedHeight(17)
        row.setStyleSheet("background-color: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(0)

        lvl_color = LEVEL_COLORS.get(entry['level'], '#aaaaaa')

        def cell(text, width=None, color='#aaaaaa'):
            lbl = QLabel(text)
            lbl.setFont(QFont("Courier New", 8))
            lbl.setStyleSheet(f"color: {color};")
            lbl.setWordWrap(False)
            if width:
                lbl.setFixedWidth(width)
            return lbl

        layout.addWidget(cell(entry['time_str'],                     68, '#333333'))
        layout.addWidget(cell(f"[{entry['level'].upper():<7}]",      80, lvl_color))
        layout.addWidget(cell(f"[{entry['module']:<10}]",           108, '#2a4a2a'))
        msg = cell(entry['message'], color=lvl_color)
        msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(msg, 1)

        return row

    # ─────────────────────────────────────────────────────────────────── export

    def _export(self):
        default = f"profiler_machine_{time.strftime('%Y%m%d_%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export System Log", default,
            "Log files (*.log);;Text files (*.txt)"
        )
        if not path:
            return
        try:
            self._logger.export(path)
            self._status_lbl.setText(f"Exported → {os.path.basename(path)}")
        except Exception as e:
            self._status_lbl.setText(f"Export failed: {e}")