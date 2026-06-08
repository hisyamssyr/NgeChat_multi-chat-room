"""Reusable modal dialogs for the Multi-Chat Room GUI."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from client.gui.styles import BG_SURFACE, BLUE, TEXT_MUTED

class _BaseDialog(QDialog):
    """Shared base with standard button row and OK/Cancel logic."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 20, 24, 20)
        self._layout.setSpacing(14)

        # Subclasses call _build_body() then _build_buttons()

    def _build_buttons(self, ok_text: str = "OK") -> None:
        """Add the OK / Cancel button row."""
        row = QHBoxLayout()
        row.setSpacing(10)

        self._ok_btn = QPushButton(ok_text)
        self._ok_btn.setObjectName("accent_btn")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_ok)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)

        row.addStretch()
        row.addWidget(self._cancel_btn)
        row.addWidget(self._ok_btn)
        self._layout.addLayout(row)

    def _on_ok(self) -> None:
        """Subclasses override to validate before accept()."""
        self.accept()

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setObjectName("field_label")
        return lbl

# CreateRoomDialog

class CreateRoomDialog(_BaseDialog):
    """Dialog to create a new chat room."""

    def __init__(self, parent=None) -> None:
        super().__init__("Create New Room", parent)
        self.room_name: str = ""
        self._build_body()
        self._build_buttons(ok_text="Create Room")

    def _build_body(self) -> None:
        title = QLabel("🏠  Create a New Room")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._layout.addWidget(title)

        hint = QLabel(
            "Choose a unique name. An invite code will be generated automatically — "
            "share it with anyone you want to let in."
        )
        hint.setObjectName("status_label")
        hint.setWordWrap(True)
        self._layout.addWidget(hint)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #30363d;")
        self._layout.addWidget(line)

        self._layout.addWidget(self._field_label("Room Name"))
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g.  AI, Gaming, Random")
        self._name_input.setMaxLength(64)
        self._name_input.returnPressed.connect(self._on_ok)
        self._layout.addWidget(self._name_input)

        self._error = QLabel("")
        self._error.setObjectName("error_label")
        self._error.hide()
        self._layout.addWidget(self._error)

    def _on_ok(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            self._error.setText("Room name cannot be empty.")
            self._error.show()
            return
        if len(name) > 64:
            self._error.setText("Room name must be 64 characters or fewer.")
            self._error.show()
            return
        self.room_name = name
        self.accept()

# PrivateMsgDialog

class PrivateMsgDialog(_BaseDialog):
    """Dialog to compose a private message."""

    def __init__(self, prefill_target: str = "", parent=None) -> None:
        super().__init__("Send Private Message", parent)
        self.target:  str = ""
        self.message: str = ""
        self._prefill = prefill_target
        self._build_body()
        self._build_buttons(ok_text="Send  ✉")
        self.setMinimumSize(420, 320)
        # Center on parent or screen
        if parent:
            pg = parent.geometry()
            self.move(
                pg.x() + (pg.width()  - self.minimumWidth())  // 2,
                pg.y() + (pg.height() - self.minimumHeight()) // 2,
            )

    def _build_body(self) -> None:
        title = QLabel("✉  Private Message")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._layout.addWidget(title)

        hint = QLabel("This message is only visible to the recipient.")
        hint.setObjectName("status_label")
        self._layout.addWidget(hint)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #30363d;")
        self._layout.addWidget(line)

        # Target input
        self._layout.addWidget(self._field_label("To (username)"))
        self._target_input = QLineEdit()
        self._target_input.setPlaceholderText("Enter username…")
        if self._prefill:
            self._target_input.setText(self._prefill)
            self._target_input.setReadOnly(True)
            self._target_input.setStyleSheet("color: #58a6ff;")
        self._layout.addWidget(self._target_input)

        # Message input
        self._layout.addWidget(self._field_label("Message"))
        self._msg_input = QTextEdit()
        self._msg_input.setObjectName("msg_input")
        self._msg_input.setPlaceholderText("Type your private message here…")
        self._msg_input.setFixedHeight(90)
        self._layout.addWidget(self._msg_input)

        # Error label
        self._error = QLabel("")
        self._error.setObjectName("error_label")
        self._error.hide()
        self._layout.addWidget(self._error)

    def _on_ok(self) -> None:
        target  = self._target_input.text().strip()
        message = self._msg_input.toPlainText().strip()

        if not target:
            self._error.setText("Please enter a target username.")
            self._error.show()
            return
        if not message:
            self._error.setText("Message cannot be empty.")
            self._error.show()
            return

        self.target  = target
        self.message = message
        self.accept()

# JoinPasswordDialog

class JoinPasswordDialog(_BaseDialog):
    """Dialog shown when joining a room that requires an invite code."""

    def __init__(self, room_name: str, parent=None) -> None:
        super().__init__("Invite Code Required", parent)
        self.password:  str = ""    # attribute name kept for back-compat
        self._room_name = room_name
        self._build_body()
        self._build_buttons(ok_text="Join Room  🔓")
        self.setMinimumSize(400, 280)
        if parent:
            pg = parent.geometry()
            self.move(
                pg.x() + (pg.width()  - self.minimumWidth())  // 2,
                pg.y() + (pg.height() - self.minimumHeight()) // 2,
            )

    def _build_body(self) -> None:
        title = QLabel("🔒  Private Room")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._layout.addWidget(title)

        hint = QLabel(
            f"Room <b>{self._room_name}</b> requires an invite code to join."
        )
        hint.setObjectName("status_label")
        hint.setWordWrap(True)
        self._layout.addWidget(hint)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #30363d;")
        self._layout.addWidget(line)

        self._layout.addWidget(self._field_label("Invite Code (8 characters)"))

        code_row = QHBoxLayout()
        self._pw_input = QLineEdit()
        self._pw_input.setPlaceholderText("e.g.  A3BX92ZK")
        self._pw_input.setMaxLength(8)
        self._pw_input.setEchoMode(QLineEdit.EchoMode.Normal)
        self._pw_input.returnPressed.connect(self._on_ok)
        # Make it uppercase automatically.
        self._pw_input.textChanged.connect(
            lambda t: self._pw_input.setText(t.upper()) if t != t.upper() else None
        )
        code_row.addWidget(self._pw_input)
        self._layout.addLayout(code_row)

        self._error = QLabel("")
        self._error.setObjectName("error_label")
        self._error.hide()
        self._layout.addWidget(self._error)

    def show_error(self, message: str) -> None:
        """Call externally to show 'wrong code' inline error."""
        self._error.setText(message)
        self._error.show()

    def _on_ok(self) -> None:
        code = self._pw_input.text().strip().upper()
        if not code:
            self._error.setText("Invite code cannot be empty.")
            self._error.show()
            return
        if len(code) != 8:
            self._error.setText("Invite code must be exactly 8 characters.")
            self._error.show()
            return
        self.password = code
        self.accept()

# RoomCodeDialog

class RoomCodeDialog(_BaseDialog):
    """Shown to the room creator immediately after the room is created."""

    def __init__(self, room_name: str, code: str, parent=None) -> None:
        super().__init__("🎉  Room Created!", parent)
        self._room_name = room_name
        self._code      = code
        self._build_body()
        # Only an OK/Close button — no cancel.
        ok_btn = QPushButton("Got it!  ✔")
        ok_btn.setObjectName("send_btn")
        ok_btn.setFixedHeight(36)
        ok_btn.clicked.connect(self.accept)
        self._layout.addWidget(ok_btn)
        self.setMinimumSize(420, 310)
        if parent:
            pg = parent.geometry()
            self.move(
                pg.x() + (pg.width()  - self.minimumWidth())  // 2,
                pg.y() + (pg.height() - self.minimumHeight()) // 2,
            )

    def _build_body(self) -> None:
        title = QLabel("🎉  Room Created!")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._layout.addWidget(title)

        info = QLabel(
            f"Room <b>{self._room_name}</b> is ready.<br>"
            "Share the invite code below with people you want to let in."
        )
        info.setObjectName("status_label")
        info.setWordWrap(True)
        self._layout.addWidget(info)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #30363d;")
        self._layout.addWidget(line)

        self._layout.addWidget(self._field_label("Invite Code"))

        code_row = QHBoxLayout()
        self._code_display = QLineEdit(self._code)
        self._code_display.setReadOnly(True)
        self._code_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._code_display.setStyleSheet(
            "font-size: 22px; font-weight: bold; font-family: monospace;"
            "letter-spacing: 4px; color: #58a6ff; background: #161b22;"
            "border: 1px solid #30363d; border-radius: 6px; padding: 8px;"
        )
        code_row.addWidget(self._code_display)

        copy_btn = QPushButton("📋  Copy")
        copy_btn.setObjectName("accent_btn")
        copy_btn.setFixedWidth(90)
        copy_btn.setFixedHeight(36)
        copy_btn.clicked.connect(self._copy_code)
        code_row.addWidget(copy_btn)
        self._layout.addLayout(code_row)

        note = QLabel("⚠️ This code won’t be shown again. Write it down!")
        note.setObjectName("error_label")
        note.setWordWrap(True)
        self._layout.addWidget(note)

    def _copy_code(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._code)

