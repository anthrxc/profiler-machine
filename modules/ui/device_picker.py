# modules/ui/device_picker.py
# Terminal-aesthetic device selection dialog shown after the loading screen.
# Presents detected video input devices as a checkable list; returns the
# indices the operator selects.

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QPushButton, QWidget, QScrollArea, QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

WINDOW_W = 620
CHECKBOX_STYLE = """
QCheckBox {
    color: #aaaaaa;
    font-family: 'Courier New';
    font-size: 11pt;
    spacing: 10px;
    padding: 4px 0px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #444444;
    background: #0a0a0a;
}
QCheckBox::indicator:checked {
    background: #00aa44;
    border: 1px solid #00cc55;
}
QCheckBox:hover {
    color: #ffffff;
}
"""

BTN_STYLE = """
QPushButton {
    background-color: #0a0a0a;
    color: #aaaaaa;
    border: 1px solid #333333;
    font-family: 'Courier New';
    font-size: 10pt;
    padding: 6px 24px;
}
QPushButton:hover {
    background-color: #111111;
    color: #ffffff;
    border: 1px solid #555555;
}
QPushButton:pressed {
    background-color: #001a0a;
    border: 1px solid #00aa44;
    color: #00cc55;
}
QPushButton:disabled {
    color: #333333;
    border: 1px solid #1a1a1a;
}
"""


def _divider():
    lbl = QLabel("═" * 68)
    lbl.setFont(QFont("Courier New", 9))
    lbl.setStyleSheet("color: #333333; margin: 0px;")
    return lbl


class DevicePickerDialog(QDialog):
    """Multi-select dialog for video input source selection.

    devices — list of dicts from device_enumerator.enumerate_devices()
    """

    def __init__(self, devices, parent=None):
        super().__init__(parent)
        self._devices = devices
        self._checkboxes = []
        self._selected = []
        self._init_ui()

    def _init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setStyleSheet("background-color: #000000;")
        self.setFixedWidth(WINDOW_W)

        root = QVBoxLayout()
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(0)
        self.setLayout(root)

        # ── Header ──────────────────────────────────────────────────────────
        title = QLabel("PROFILER MACHINE // FEED SELECTION")
        title.setFont(QFont("Courier New", 12, QFont.Bold))
        title.setStyleSheet("color: #ffffff; margin-bottom: 6px;")
        root.addWidget(title)
        root.addWidget(_divider())

        subtitle = QLabel("Select video input sources to initialize:")
        subtitle.setFont(QFont("Courier New", 10))
        subtitle.setStyleSheet("color: #666666; margin-top: 10px; margin-bottom: 10px;")
        root.addWidget(subtitle)

        # ── Device list ──────────────────────────────────────────────────────
        if not self._devices:
            none_label = QLabel("  No video input devices detected.")
            none_label.setFont(QFont("Courier New", 10))
            none_label.setStyleSheet("color: #555555; padding: 8px 0px;")
            root.addWidget(none_label)
        else:
            scroll_content = QWidget()
            scroll_content.setStyleSheet("background-color: #000000;")
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setContentsMargins(0, 0, 0, 0)
            scroll_layout.setSpacing(2)

            for dev in self._devices:
                cb = self._make_device_checkbox(dev)
                scroll_layout.addWidget(cb)
                self._checkboxes.append((cb, dev))

            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setWidget(scroll_content)
            scroll_area.setStyleSheet("""
                QScrollArea { border: none; background: #000000; }
                QScrollBar:vertical {
                    background: #0a0a0a; width: 6px;
                }
                QScrollBar::handle:vertical {
                    background: #333333; min-height: 20px;
                }
            """)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            max_visible = min(len(self._devices), 6)
            scroll_area.setFixedHeight(max_visible * 36 + 4)
            root.addWidget(scroll_area)

        # ── Footer ───────────────────────────────────────────────────────────
        root.addSpacing(10)
        root.addWidget(_divider())
        root.addSpacing(10)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)

        self._status_label = QLabel("0 source(s) selected")
        self._status_label.setFont(QFont("Courier New", 9))
        self._status_label.setStyleSheet("color: #555555;")
        footer_row.addWidget(self._status_label)
        footer_row.addStretch()

        self._confirm_btn = QPushButton("CONFIRM")
        self._confirm_btn.setFont(QFont("Courier New", 10, QFont.Bold))
        self._confirm_btn.setStyleSheet(BTN_STYLE)
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(self._on_confirm)
        footer_row.addWidget(self._confirm_btn)

        skip_btn = QPushButton("SKIP")
        skip_btn.setFont(QFont("Courier New", 10))
        skip_btn.setStyleSheet(BTN_STYLE)
        skip_btn.clicked.connect(self.reject)
        footer_row.addWidget(skip_btn)

        root.addLayout(footer_row)
        self.adjustSize()

    def _make_device_checkbox(self, dev):
        res = f"{dev['width']}×{dev['height']}"
        name = dev['name']
        label = f"  [{dev['index']}]  {res:<12}  {name}"
        cb = QCheckBox(label)
        cb.setStyleSheet(CHECKBOX_STYLE)
        cb.stateChanged.connect(self._on_selection_changed)
        return cb

    def _on_selection_changed(self):
        count = sum(1 for cb, _ in self._checkboxes if cb.isChecked())
        self._status_label.setText(f"{count} source(s) selected")
        color = "#00aa44" if count > 0 else "#555555"
        self._status_label.setStyleSheet(f"color: {color};")
        self._confirm_btn.setEnabled(count > 0)

    def _on_confirm(self):
        self._selected = [dev for cb, dev in self._checkboxes if cb.isChecked()]
        self.accept()

    def get_selected(self):
        """Return list of selected device dicts."""
        return self._selected


def pick_devices(devices, qt_app=None):
    """Show the device picker and return the list of selected device dicts.

    Returns an empty list if the user skips or closes without selecting.
    """
    dlg = DevicePickerDialog(devices)

    # Centre on screen
    from PyQt5.QtWidgets import QDesktopWidget
    geo = QDesktopWidget().screenGeometry()
    dlg.move(
        (geo.width()  - WINDOW_W)  // 2,
        (geo.height() - dlg.sizeHint().height()) // 2,
    )

    if dlg.exec_() == QDialog.Accepted:
        return dlg.get_selected()
    return []