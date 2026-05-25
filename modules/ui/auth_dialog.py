# modules/ui/auth_dialog.py
# Terminal-aesthetic credential dialog for video feeds that require authentication.
# Shown automatically after the first failed connection attempt on a bare network URL.

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

WINDOW_W = 560

_BTN_STYLE = """
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

_INPUT_STYLE = """
QLineEdit {
    background-color: #0d0d0d;
    color: #ffffff;
    border: 1px solid #333333;
    font-family: 'Courier New';
    font-size: 10pt;
    padding: 5px 8px;
    selection-background-color: #1a3a1a;
}
QLineEdit:focus {
    border: 1px solid #00aa44;
}
QLineEdit::placeholder {
    color: #333333;
}
"""


def _divider():
    lbl = QLabel("═" * 58)
    lbl.setFont(QFont("Courier New", 9))
    lbl.setStyleSheet("color: #333333; margin: 0px;")
    return lbl


def _field_row(label_text, widget):
    """Lay out a label + input on one row."""
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    lbl = QLabel(label_text)
    lbl.setFont(QFont("Courier New", 10))
    lbl.setStyleSheet("color: #666666;")
    lbl.setFixedWidth(90)
    layout.addWidget(lbl)
    layout.addWidget(widget)
    return row


class AuthDialog(QDialog):
    """Prompts the operator for username and password.

    Shown when a network feed fails its first connection attempt and no
    credentials were provided inline in the URL.
    """

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self._source   = source
        self._username = ''
        self._password = ''
        self._init_ui()

    def _init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setFixedWidth(WINDOW_W)
        self.setStyleSheet("background-color: #000000;")

        root = QVBoxLayout()
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(6)
        self.setLayout(root)

        # ── Header ────────────────────────────────────────────────────────────
        title = QLabel("PROFILER MACHINE // FEED AUTH")
        title.setFont(QFont("Courier New", 12, QFont.Bold))
        title.setStyleSheet("color: #ffffff; margin-bottom: 4px;")
        root.addWidget(title)
        root.addWidget(_divider())

        root.addSpacing(10)

        info = QLabel("Authentication may be required for:")
        info.setFont(QFont("Courier New", 9))
        info.setStyleSheet("color: #555555;")
        root.addWidget(info)

        # Source URL (truncated if long)
        src_str = str(self._source)
        if len(src_str) > 62:
            src_str = '...' + src_str[-59:]
        src_label = QLabel(src_str)
        src_label.setFont(QFont("Courier New", 9))
        src_label.setStyleSheet("color: #888888; padding-bottom: 8px;")
        src_label.setWordWrap(True)
        root.addWidget(src_label)

        hint = QLabel("Leave blank and press CONFIRM to retry without credentials, or SKIP to cancel.")
        hint.setFont(QFont("Courier New", 8))
        hint.setStyleSheet("color: #444444; padding-bottom: 4px;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(_divider())
        root.addSpacing(12)

        # ── Credential fields ─────────────────────────────────────────────────
        self._username_input = QLineEdit()
        self._username_input.setStyleSheet(_INPUT_STYLE)
        self._username_input.setPlaceholderText("username")
        self._username_input.returnPressed.connect(lambda: self._password_input.setFocus())
        root.addWidget(_field_row("Username:", self._username_input))

        root.addSpacing(8)

        self._password_input = QLineEdit()
        self._password_input.setStyleSheet(_INPUT_STYLE)
        self._password_input.setEchoMode(QLineEdit.Password)
        self._password_input.setPlaceholderText("password")
        self._password_input.returnPressed.connect(self._on_confirm)
        root.addWidget(_field_row("Password:", self._password_input))

        root.addSpacing(16)
        root.addWidget(_divider())
        root.addSpacing(10)

        # ── Footer ────────────────────────────────────────────────────────────
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.addStretch()

        self._confirm_btn = QPushButton("CONFIRM")
        self._confirm_btn.setFont(QFont("Courier New", 10, QFont.Bold))
        self._confirm_btn.setStyleSheet(_BTN_STYLE)
        self._confirm_btn.clicked.connect(self._on_confirm)
        footer_row.addWidget(self._confirm_btn)

        skip_btn = QPushButton("SKIP")
        skip_btn.setFont(QFont("Courier New", 10))
        skip_btn.setStyleSheet(_BTN_STYLE)
        skip_btn.clicked.connect(self.reject)
        footer_row.addWidget(skip_btn)

        root.addLayout(footer_row)
        self.adjustSize()

        self._username_input.setFocus()

    def _on_confirm(self):
        self._username = self._username_input.text()
        self._password = self._password_input.text()
        self.accept()

    def get_credentials(self):
        """Return (username, password) after the dialog is accepted."""
        return self._username, self._password


def show_auth_dialog(source, feed_id, parent=None):
    """Display the auth dialog and return (username, password) or None if skipped."""
    dlg = AuthDialog(source, parent=parent)
    dlg.adjustSize()

    if parent:
        pg = parent.frameGeometry()
        dlg.move(
            pg.x() + (pg.width()  - dlg.width())  // 2,
            pg.y() + (pg.height() - dlg.height()) // 2,
        )
    else:
        from PyQt5.QtWidgets import QDesktopWidget
        geo = QDesktopWidget().screenGeometry()
        dlg.move(
            (geo.width()  - dlg.width())  // 2,
            (geo.height() - dlg.height()) // 2,
        )

    if dlg.exec_() == QDialog.Accepted:
        return dlg.get_credentials()
    return None