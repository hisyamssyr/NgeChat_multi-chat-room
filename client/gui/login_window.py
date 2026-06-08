"""
client/gui/login_window.py
--------------------------
Login / Register dialog shown before the main window appears.

Flow
----
1. User fills in Host, Port, Username, Password.
2. Clicks [Login] or [Register then Login].
3. LoginWindow creates a NetworkClient, connects, sends the packet.
4. The receiver thread emits packet_received → _on_packet() runs in
   the Qt event loop (which is active inside dialog.exec()).
5. On "ok":  dialog.accept() → gui_main picks up network + username.
6. On "error": show inline error label, let user retry.

The existing CLI client (client.py) is completely untouched.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QWidget,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon

from client.network_client import NetworkClient
from client.gui.styles import (
    BG_DEEP, BG_SURFACE, BLUE, GREEN, RED, TEXT, TEXT_MUTED, BORDER,
)


class LoginWindow(QDialog):
    """
    Modal login / register form.

    After exec() returns Accepted:
        self.network_client  — connected NetworkClient instance
        self.username        — authenticated username (str)
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Multi-Chat Room — Sign In")
        self.setModal(True)
        self.setFixedSize(440, 560)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        # Public outputs (set on accept)
        self.network_client: NetworkClient | None = None
        self.username: str = ""

        # Internal state
        self._pending_action: str | None = None   # "login" | "register"
        self._reg_username:   str = ""
        self._reg_password:   str = ""

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Outer wrapper for centering the card
        wrapper = QWidget()
        wrapper.setStyleSheet(f"background-color: {BG_DEEP};")
        wlayout = QVBoxLayout(wrapper)
        wlayout.setContentsMargins(30, 30, 30, 30)
        wlayout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ── Card ──────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("login_card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 32, 32, 32)
        card_layout.setSpacing(16)

        # Logo + title
        title_lbl = QLabel("🗨 Multi-Chat Room")
        title_lbl.setObjectName("login_title")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title_lbl)

        subtitle = QLabel("Sign in to start chatting")
        subtitle.setObjectName("login_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(8)

        # ── Username ──────────────────────────────────────────────────
        lbl_user = QLabel("USERNAME")
        lbl_user.setObjectName("field_label")
        card_layout.addWidget(lbl_user)

        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("Enter your username")
        self._username_input.setMaxLength(32)
        self._username_input.returnPressed.connect(self._focus_password)
        card_layout.addWidget(self._username_input)

        # ── Password ──────────────────────────────────────────────────
        lbl_pass = QLabel("PASSWORD")
        lbl_pass.setObjectName("field_label")
        card_layout.addWidget(lbl_pass)

        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("Enter your password")
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.returnPressed.connect(self._on_login_clicked)
        card_layout.addWidget(self._password_input)

        # ── Status / error label ──────────────────────────────────────
        self._status_label = QLabel("")
        self._status_label.setObjectName("status_label")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.hide()
        card_layout.addWidget(self._status_label)

        card_layout.addSpacing(4)

        # ── Login button ──────────────────────────────────────────────
        self._login_btn = QPushButton("Login")
        self._login_btn.setObjectName("login_btn")
        self._login_btn.setFixedHeight(40)
        self._login_btn.clicked.connect(self._on_login_clicked)
        card_layout.addWidget(self._login_btn)

        # ── Register button ───────────────────────────────────────────
        self._register_btn = QPushButton("Register New Account")
        self._register_btn.setObjectName("register_btn")
        self._register_btn.setFixedHeight(38)
        self._register_btn.clicked.connect(self._on_register_clicked)
        card_layout.addWidget(self._register_btn)

        card_layout.addSpacing(8)

        # ── Divider ───────────────────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"color: {BORDER};")
        card_layout.addWidget(div)

        # ── Server connection fields ───────────────────────────────────
        lbl_srv = QLabel("SERVER CONNECTION")
        lbl_srv.setObjectName("field_label")
        card_layout.addWidget(lbl_srv)

        srv_row = QHBoxLayout()
        srv_row.setSpacing(8)

        self._host_input = QLineEdit("127.0.0.1")
        self._host_input.setObjectName("server_input")
        self._host_input.setPlaceholderText("Host")
        srv_row.addWidget(self._host_input, 3)

        colon = QLabel(":")
        colon.setStyleSheet(f"color: {TEXT_MUTED};")
        colon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        srv_row.addWidget(colon)

        self._port_input = QLineEdit("9090")
        self._port_input.setObjectName("server_input")
        self._port_input.setPlaceholderText("Port")
        self._port_input.setMaxLength(5)
        self._port_input.setFixedWidth(72)
        srv_row.addWidget(self._port_input)

        card_layout.addLayout(srv_row)

        wlayout.addWidget(card)
        root.addWidget(wrapper)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _focus_password(self) -> None:
        self._password_input.setFocus()

    def _set_busy(self, busy: bool) -> None:
        """Disable/enable buttons during an async operation."""
        self._login_btn.setEnabled(not busy)
        self._register_btn.setEnabled(not busy)
        self._username_input.setReadOnly(busy)
        self._password_input.setReadOnly(busy)
        self._host_input.setReadOnly(busy)
        self._port_input.setReadOnly(busy)

    def _show_status(self, text: str, color: str = TEXT_MUTED) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._status_label.show()

    def _show_error(self, text: str) -> None:
        self._show_status(f"✗  {text}", RED)
        self._set_busy(False)

    def _show_info(self, text: str) -> None:
        self._show_status(f"✓  {text}", GREEN)

    # ------------------------------------------------------------------
    # Network helpers
    # ------------------------------------------------------------------

    def _get_or_connect(self) -> tuple[bool, str]:
        """
        Return the existing connected NetworkClient, or create + connect one.
        """
        host = self._host_input.text().strip()
        try:
            port = int(self._port_input.text().strip())
        except ValueError:
            return False, "Port must be a number."

        if self.network_client and self.network_client.is_connected:
            return True, ""

        # Create new client and connect.
        nc = NetworkClient(host, port)
        ok, err = nc.connect_to_server()
        if not ok:
            return False, err

        # Wire packet signal; disconnect any previous connection first.
        nc.packet_received.connect(self._on_packet)
        self.network_client = nc
        return True, ""

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_login_clicked(self) -> None:
        username = self._username_input.text().strip()
        password = self._password_input.text()

        if not username:
            self._show_error("Please enter a username.")
            return
        if not password:
            self._show_error("Please enter a password.")
            return

        self._set_busy(True)
        self._show_status("Connecting…", TEXT_MUTED)

        ok, err = self._get_or_connect()
        if not ok:
            self._show_error(err)
            return

        self._pending_action = "login"
        self._show_status("Authenticating…", TEXT_MUTED)
        self.network_client.send_login(username, password)

    def _on_register_clicked(self) -> None:
        username = self._username_input.text().strip()
        password = self._password_input.text()

        if not username:
            self._show_error("Please enter a username.")
            return
        if not password:
            self._show_error("Please enter a password.")
            return
        if len(password) < 3:
            self._show_error("Password must be at least 3 characters.")
            return

        self._set_busy(True)
        self._show_status("Connecting…", TEXT_MUTED)

        ok, err = self._get_or_connect()
        if not ok:
            self._show_error(err)
            return

        # Save credentials — after register ok, we auto-login.
        self._reg_username = username
        self._reg_password = password
        self._pending_action = "register"
        self._show_status("Registering…", TEXT_MUTED)
        self.network_client.send_register(username, password)

    # ------------------------------------------------------------------
    # Packet handler (called in GUI thread via Qt signal)
    # ------------------------------------------------------------------

    def _on_packet(self, packet: dict) -> None:
        status = packet.get("status")
        msg    = packet.get("message", "")

        if status == "ok":
            if self._pending_action == "register":
                # Auto-login after successful registration.
                self._show_info("Registered! Logging in…")
                self._pending_action = "login"
                self.network_client.send_login(
                    self._reg_username, self._reg_password
                )

            elif self._pending_action == "login":
                self.username = self._username_input.text().strip()
                self._show_info(f"Welcome, {self.username}!")
                self.accept()   # closes the dialog

        elif status == "error":
            self._show_error(msg)
            self._pending_action = None
