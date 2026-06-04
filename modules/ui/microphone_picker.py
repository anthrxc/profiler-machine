# modules/ui/microphone_picker.py
# Terminal-aesthetic microphone selection dialog, matching device_picker.py style.

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QPushButton, QWidget, QScrollArea, QButtonGroup
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

WINDOW_W = 580

RADIO_STYLE = """
QRadioButton {
    color: #aaaaaa;
    font-family: 'Courier New';
    font-size: 11pt;
    spacing: 10px;
    padding: 4px 0px;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #444444;
    background: #0a0a0a;
}
QRadioButton::indicator:checked {
    background: #00aa44;
    border: 1px solid #00cc55;
}
QRadioButton:hover {
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
    lbl = QLabel("═" * 66)
    lbl.setFont(QFont("Courier New", 9))
    lbl.setStyleSheet("color: #333333; margin: 0px;")
    return lbl


class MicrophonePickerDialog(QDialog):
    """Single-select dialog for microphone device selection."""

    def __init__(self, devices, parent=None):
        super().__init__(parent)
        self._devices = devices  # list of (device_id, device_name)
        self._button_group = QButtonGroup(self)
        self._id_map = {}        # button_group id → sounddevice device_id
        self._selected_device_id = None
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
        title = QLabel("PROFILER MACHINE // MICROPHONE SELECTION")
        title.setFont(QFont("Courier New", 12, QFont.Bold))
        title.setStyleSheet("color: #ffffff; margin-bottom: 6px;")
        root.addWidget(title)
        root.addWidget(_divider())

        subtitle = QLabel("Select audio input device:")
        subtitle.setFont(QFont("Courier New", 10))
        subtitle.setStyleSheet("color: #666666; margin-top: 10px; margin-bottom: 10px;")
        root.addWidget(subtitle)

        # ── Device list ──────────────────────────────────────────────────────
        if not self._devices:
            none_label = QLabel("  No audio input devices detected.")
            none_label.setFont(QFont("Courier New", 10))
            none_label.setStyleSheet("color: #555555; padding: 8px 0px;")
            root.addWidget(none_label)
        else:
            scroll_content = QWidget()
            scroll_content.setStyleSheet("background-color: #000000;")
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setContentsMargins(0, 0, 0, 0)
            scroll_layout.setSpacing(2)

            for i, (device_id, device_name) in enumerate(self._devices):
                rb = self._make_device_radio(device_name)
                scroll_layout.addWidget(rb)
                self._button_group.addButton(rb, i)
                self._id_map[i] = device_id
                if i == 0:
                    rb.setChecked(True)

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
        footer_row.addStretch()

        confirm_btn = QPushButton("CONFIRM")
        confirm_btn.setFont(QFont("Courier New", 10, QFont.Bold))
        confirm_btn.setStyleSheet(BTN_STYLE)
        confirm_btn.clicked.connect(self._on_confirm)
        footer_row.addWidget(confirm_btn)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFont(QFont("Courier New", 10))
        cancel_btn.setStyleSheet(BTN_STYLE)
        cancel_btn.clicked.connect(self.reject)
        footer_row.addWidget(cancel_btn)

        root.addLayout(footer_row)
        self.adjustSize()

    def _make_device_radio(self, device_name):
        rb = QRadioButton(f"  {device_name}")
        rb.setStyleSheet(RADIO_STYLE)
        return rb

    def _on_confirm(self):
        btn_id = self._button_group.checkedId()
        if btn_id != -1 and btn_id in self._id_map:
            self._selected_device_id = self._id_map[btn_id]
            self.accept()

    def get_selected_device_id(self):
        """Return the selected device ID, or None if cancelled."""
        return self._selected_device_id


def pick_microphone(devices, parent=None):
    """Show mic picker and return selected device_id or None if cancelled.
    
    devices — list of (device_id, device_name) tuples
    """
    dlg = MicrophonePickerDialog(devices, parent)

    # Centre on screen
    from PyQt5.QtWidgets import QDesktopWidget
    geo = QDesktopWidget().screenGeometry()
    dlg.move(
        (geo.width()  - WINDOW_W)  // 2,
        (geo.height() - dlg.sizeHint().height()) // 2,
    )

    if dlg.exec_() == QDialog.Accepted:
        return dlg.get_selected_device_id()
    return None