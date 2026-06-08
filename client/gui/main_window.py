import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QTextBrowser, QTextEdit, QFrame, QSplitter, QStatusBar,
    QSizePolicy, QMenu,
)
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSlot
from PyQt6.QtGui import QFont, QKeyEvent

from client.network_client import NetworkClient
from client.gui.dialogs import (
    CreateRoomDialog, PrivateMsgDialog, JoinPasswordDialog,
    RoomCodeDialog, AddFriendDialog,
)
from client.gui.styles import (
    BLUE, GREEN, RED, PURPLE, AMBER,
    TEXT, TEXT_MUTED, BG_SURFACE, BG_ELEVATED, BORDER,
    OWN_MSG_BG, PM_BG, NOTIF_COLOR,
)


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def _fmt_ts(timestamp: str) -> str:
    try:
        return timestamp.split(" ")[1][:5]
    except Exception:
        return ""


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
    )


def _html_broadcast(sender: str, message: str, timestamp: str, is_own: bool) -> str:
    ts  = _fmt_ts(timestamp)
    msg = _escape(message)

    if is_own:
        return (
            '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
            ' style="margin:3px 0;">'
            '<tr>'
            '<td width="20%"></td>'
            '<td align="right" style="padding:0 10px 0 0;">'
            f'<div style="'
            f'display:inline-block;'
            f'background-color:#1a3a5c;'
            f'border-radius:16px 2px 16px 16px;'
            f'padding:10px 14px 7px 14px;'
            f'max-width:100%;'
            f'">'
            f'<div style="color:#c9d1d9; font-size:13px;">{msg}</div>'
            f'<div style="color:#6e8ab0; font-size:10px; text-align:right; margin-top:5px;">'
            f'&#10003; {ts}</div>'
            '</div>'
            '</td>'
            '</tr>'
            '</table>'
        )
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:3px 0;">'
        '<tr>'
        '<td align="left" style="padding:0 0 0 10px;">'
        f'<div style="'
        f'display:inline-block;'
        f'background-color:#21262d;'
        f'border-radius:2px 16px 16px 16px;'
        f'padding:10px 14px 7px 14px;'
        f'max-width:80%;'
        f'">'
        f'<div style="color:#58a6ff; font-size:11px; font-weight:bold;'
        f' margin-bottom:4px;">{_escape(sender)}</div>'
        f'<div style="color:#c9d1d9; font-size:13px;">{msg}</div>'
        f'<div style="color:#6e7681; font-size:10px; margin-top:5px;">{ts}</div>'
        '</div>'
        '</td>'
        '<td width="20%"></td>'
        '</tr>'
        '</table>'
    )


def _html_private(sender: str, message: str, timestamp: str) -> str:
    ts  = _fmt_ts(timestamp)
    msg = _escape(message)
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:3px 0;">'
        '<tr>'
        '<td align="left" style="padding:0 0 0 10px;">'
        f'<div style="'
        f'display:inline-block;'
        f'background-color:#2d1b4e;'
        f'border-radius:2px 16px 16px 16px;'
        f'border-left:3px solid #a78bfa;'
        f'padding:10px 14px 7px 14px;'
        f'max-width:80%;'
        f'">'
        f'<div style="color:#a78bfa; font-size:11px; font-weight:bold;'
        f' margin-bottom:4px;">&#128233; {_escape(sender)} &nbsp;<span'
        f' style="font-style:italic; font-weight:normal; color:#8b6fc7;">private</span></div>'
        f'<div style="color:#c9d1d9; font-size:13px;">{msg}</div>'
        f'<div style="color:#6e7681; font-size:10px; margin-top:5px;">{ts}</div>'
        '</div>'
        '</td>'
        '<td width="20%"></td>'
        '</tr>'
        '</table>'
    )


def _html_notification(message: str) -> str:
    msg = _escape(message)
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:6px 0;">'
        '<tr>'
        '<td align="center">'
        f'<span style="'
        f'color:#484f58;'
        f'font-size:11px;'
        f'font-style:italic;'
        f'background-color:#161b22;'
        f'border-radius:10px;'
        f'padding:3px 12px;'
        f'">{msg}</span>'
        '</td>'
        '</tr>'
        '</table>'
    )


def _html_history_separator(room: str) -> str:
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:10px 0;">'
        '<tr>'
        '<td align="center">'
        f'<span style="'
        f'color:#30363d;'
        f'font-size:11px;'
        f'background-color:#161b22;'
        f'border-radius:8px;'
        f'padding:2px 14px;'
        f'">&#9679; History: #{_escape(room)} &#9679;</span>'
        '</td>'
        '</tr>'
        '</table>'
    )


def _html_system(message: str, color: str = TEXT_MUTED) -> str:
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:4px 0;">'
        '<tr>'
        '<td align="center">'
        f'<span style="color:{color}; font-size:12px;">{_escape(message)}</span>'
        '</td>'
        '</tr>'
        '</table>'
    )


def _html_pm_out(message: str, timestamp: str) -> str:
    ts  = _fmt_ts(timestamp)
    msg = _escape(message)
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:3px 0;">'
        '<tr>'
        '<td width="20%"></td>'
        '<td align="right" style="padding:0 10px 0 0;">'
        f'<div style="'
        f'display:inline-block;'
        f'background-color:#3b1f6e;'
        f'border-radius:16px 2px 16px 16px;'
        f'padding:10px 14px 7px 14px;'
        f'max-width:100%;'
        f'">'
        f'<div style="color:#c9d1d9; font-size:13px;">{msg}</div>'
        f'<div style="color:#9b72cf; font-size:10px; text-align:right; margin-top:5px;">&#10003; {ts}</div>'
        '</div>'
        '</td>'
        '</tr>'
        '</table>'
    )


# ---------------------------------------------------------------------------
# Custom input widget
# ---------------------------------------------------------------------------

class _MsgInput(QTextEdit):
    """QTextEdit that sends on Enter; Shift+Enter inserts a newline."""

    def __init__(self, on_send_callback, parent=None) -> None:
        super().__init__(parent)
        self._on_send = on_send_callback
        self.setObjectName("msg_input")
        self.setFixedHeight(44)
        self.setPlaceholderText("Type a message…  (Enter to send, Shift+Enter for newline)")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self._on_send()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self, network: NetworkClient, username: str) -> None:
        super().__init__()
        self._network          = network
        self._username         = username
        self._current_room: str | None       = None
        self._current_pm_target: str | None  = None
        self._joined_rooms: set[str]         = set()
        self._room_logs: dict[str, list[str]] = {}
        self._pm_logs: dict[str, list[str]]   = {}
        self._room_meta: dict[str, dict]      = {}
        self._friend_data: list[dict]         = []
        self._logged_out = False

        self.setWindowTitle(f"Multi-Chat Room  —  {username}")
        self.setMinimumSize(900, 620)
        self.resize(1100, 700)

        self._setup_ui()
        self._connect_signals()

        QTimer.singleShot(300, self._initial_fetch)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        self._notif_bar = self._build_notif_bar()
        root.addWidget(self._notif_bar)
        root.addWidget(self._build_body(), stretch=1)
        root.addWidget(self._build_input_bar())

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(f"Connected  •  Logged in as {self._username}")

    def _build_title_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("title_bar")
        bar.setFixedHeight(48)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(12)

        title = QLabel("🗨  Multi-Chat Room")
        title.setObjectName("app_title")
        h.addWidget(title)
        h.addStretch()

        user_lbl = QLabel(f"👤  {self._username}")
        user_lbl.setObjectName("username_label")
        h.addWidget(user_lbl)

        refresh_btn = QPushButton("↺  Refresh")
        refresh_btn.setObjectName("icon_btn")
        refresh_btn.setFixedWidth(90)
        refresh_btn.setToolTip("Refresh room and user lists")
        refresh_btn.clicked.connect(self._on_refresh)
        h.addWidget(refresh_btn)

        logout_btn = QPushButton("Logout")
        logout_btn.setObjectName("danger_btn")
        logout_btn.setFixedWidth(80)
        logout_btn.clicked.connect(self._on_logout)
        h.addWidget(logout_btn)

        return bar

    def _build_notif_bar(self) -> QFrame:
        """Green inline bar shown when a friend request arrives (hidden by default)."""
        bar = QFrame()
        bar.setObjectName("notif_bar")
        bar.setFixedHeight(44)
        bar.setStyleSheet("#notif_bar { background:#1f3a2d; border-bottom:1px solid #2ea043; }")
        bar.hide()

        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(10)

        self._notif_label = QLabel()
        self._notif_label.setStyleSheet("color:#3fb950; font-size:13px;")
        h.addWidget(self._notif_label, stretch=1)

        self._notif_accept_btn = QPushButton("Accept")
        self._notif_accept_btn.setObjectName("send_btn")
        self._notif_accept_btn.setFixedSize(80, 28)

        self._notif_decline_btn = QPushButton("Decline")
        self._notif_decline_btn.setObjectName("danger_btn")
        self._notif_decline_btn.setFixedSize(80, 28)

        self._notif_dismiss_btn = QPushButton("✕")
        self._notif_dismiss_btn.setObjectName("icon_btn")
        self._notif_dismiss_btn.setFixedSize(28, 28)
        self._notif_dismiss_btn.clicked.connect(self._dismiss_notif)

        h.addWidget(self._notif_accept_btn)
        h.addWidget(self._notif_decline_btn)
        h.addWidget(self._notif_dismiss_btn)

        return bar

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left panel — room list
        left = QFrame()
        left.setObjectName("left_panel")
        left.setMinimumWidth(170)
        left.setMaximumWidth(240)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 10)
        lv.setSpacing(0)

        rooms_hdr = QLabel("ROOMS")
        rooms_hdr.setObjectName("section_header")
        lv.addWidget(rooms_hdr)

        self._room_list = QListWidget()
        self._room_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._room_list.itemClicked.connect(self._on_room_clicked)
        self._room_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._room_list.customContextMenuRequested.connect(self._on_room_context_menu)
        lv.addWidget(self._room_list, stretch=1)

        add_btn = QPushButton("＋  Add Room  ▾")
        add_btn.setObjectName("accent_btn")
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet("margin: 6px 10px; border-radius: 6px;")

        add_menu = QMenu(add_btn)
        add_menu.setStyleSheet(
            "QMenu { background:#161b22; border:1px solid #30363d; color:#c9d1d9; }"
            "QMenu::item { padding:8px 20px; }"
            "QMenu::item:selected { background:#238636; border-radius:4px; }"
        )
        act_create = add_menu.addAction("🏠  Create New Room")
        act_join   = add_menu.addAction("🔑  Join with Invite Code")
        act_create.triggered.connect(self._on_create_room)
        act_join.triggered.connect(self._on_join_by_code)
        add_btn.setMenu(add_menu)
        lv.addWidget(add_btn)

        # Centre panel — chat area
        chat_frame = QFrame()
        chat_frame.setObjectName("chat_frame")
        cv = QVBoxLayout(chat_frame)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        chat_header_bar = QFrame()
        chat_header_bar.setObjectName("chat_header_bar")
        chat_header_bar.setFixedHeight(42)
        chh = QHBoxLayout(chat_header_bar)
        chh.setContentsMargins(14, 0, 14, 0)
        chh.setSpacing(10)

        self._room_name_label = QLabel("Select a room →")
        self._room_name_label.setObjectName("chat_room_name")
        chh.addWidget(self._room_name_label)
        chh.addStretch()

        self._leave_btn = QPushButton("Leave Room")
        self._leave_btn.setObjectName("danger_btn")
        self._leave_btn.setFixedHeight(28)
        self._leave_btn.clicked.connect(self._on_leave_room)
        chh.addWidget(self._leave_btn)

        cv.addWidget(chat_header_bar)

        self._chat_area = QTextBrowser()
        self._chat_area.setObjectName("chat_area")
        self._chat_area.setOpenLinks(False)
        self._chat_area.setReadOnly(True)
        cv.addWidget(self._chat_area, stretch=1)

        # Right panel — friends list
        right = QFrame()
        right.setObjectName("right_panel")
        right.setMinimumWidth(150)
        right.setMaximumWidth(210)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 10)
        rv.setSpacing(0)

        friends_hdr = QLabel("FRIENDS")
        friends_hdr.setObjectName("section_header")
        rv.addWidget(friends_hdr)

        self._user_list = QListWidget()
        self._user_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._user_list.itemClicked.connect(self._on_user_clicked)
        self._user_list.itemDoubleClicked.connect(self._on_user_clicked)
        self._user_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._user_list.customContextMenuRequested.connect(self._on_friend_context_menu)
        rv.addWidget(self._user_list, stretch=1)

        add_friend_btn = QPushButton("➕  Add Friend")
        add_friend_btn.setObjectName("accent_btn")
        add_friend_btn.setFixedHeight(34)
        add_friend_btn.setStyleSheet("margin: 6px 10px; border-radius: 6px;")
        add_friend_btn.clicked.connect(self._on_add_friend)
        rv.addWidget(add_friend_btn)

        splitter.addWidget(left)
        splitter.addWidget(chat_frame)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)  # chat area takes all extra space

        return splitter

    def _build_input_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("input_bar")
        bar.setFixedHeight(66)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(8)

        file_btn = QPushButton("📎")
        file_btn.setObjectName("icon_btn")
        file_btn.setToolTip("File Transfer — Coming Soon")
        file_btn.setEnabled(False)
        h.addWidget(file_btn)

        voice_btn = QPushButton("🎤")
        voice_btn.setObjectName("icon_btn")
        voice_btn.setToolTip("Voice Chat — Coming Soon")
        voice_btn.setEnabled(False)
        h.addWidget(voice_btn)

        self._msg_input = _MsgInput(on_send_callback=self._on_send)
        h.addWidget(self._msg_input, stretch=1)

        send_btn = QPushButton("Send  ▶")
        send_btn.setObjectName("send_btn")
        send_btn.setFixedWidth(100)
        send_btn.clicked.connect(self._on_send)
        h.addWidget(send_btn)

        return bar

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._network.packet_received.connect(self.on_packet)
        self._network.disconnected_signal.connect(self._on_disconnected)

    def _initial_fetch(self) -> None:
        self._network.send_get_rooms()
        self._network.send_get_friends()

    # ------------------------------------------------------------------
    # Packet handler (runs in the GUI thread via Qt signal)
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def on_packet(self, packet: dict) -> None:
        ptype  = packet.get("type")
        status = packet.get("status")

        if status == "ok":
            msg       = packet.get("message", "")
            room_code = packet.get("room_code")
            room_name = packet.get("room_name", "")

            if room_code:
                # Room just created — show code dialog then switch to it.
                dlg = RoomCodeDialog(room_name=room_name, code=room_code, parent=self)
                dlg.exec()
                QTimer.singleShot(300, self._network.send_get_rooms)
                QTimer.singleShot(600, lambda rn=room_name: self._switch_to_room(rn))
            elif room_name and "Joined room" in msg:
                # join_by_code success — refresh list then switch view.
                meta = self._room_meta.get(room_name, {})
                meta["is_member"] = True
                self._room_meta[room_name] = meta
                self._joined_rooms.add(room_name)
                QTimer.singleShot(300, self._network.send_get_rooms)
                QTimer.singleShot(600, lambda rn=room_name: self._switch_to_room(rn))
            else:
                self._status_bar.showMessage(f"✓  {msg}", 4000)

            # Standard join_room ack (room_name not included in this path).
            if "Joined room" in msg and not room_name:
                room = msg.split("'")[1] if "'" in msg else self._current_room
                if room:
                    self._joined_rooms.add(room)
                    self._refresh_room_list_ui()
            return

        if status == "error":
            msg = packet.get("message", "Error")
            self._status_bar.showMessage(f"✗  {msg}", 5000)
            self._append_to_chat(_html_system(f"✗  {msg}", RED))
            # Roll back optimistic join if the invite code was wrong.
            if msg == "Wrong invite code." and self._current_room:
                self._joined_rooms.discard(self._current_room)
                self._current_room = None
                self._room_name_label.setText("Select a room →")
                self._leave_btn.setText("Close Chat")
                self._refresh_room_list_ui()
            return

        if ptype == "broadcast":
            room      = packet.get("room", "")
            sender    = packet.get("sender", "?")
            message   = packet.get("message", "")
            timestamp = packet.get("timestamp", "")
            html      = _html_broadcast(sender, message, timestamp, sender == self._username)
            self._store_and_show(room, html)
            return

        if ptype == "private_message":
            sender    = packet.get("sender", "?")
            message   = packet.get("message", "")
            timestamp = packet.get("timestamp", "")
            html      = _html_private(sender, message, timestamp)
            self._store_pm(sender, html)
            if sender != self._current_pm_target:
                self._status_bar.showMessage(f"📩 New PM from {sender}", 5000)
                self._mark_user_unread(sender)
            return

        if ptype == "notification":
            room    = packet.get("room", "")
            message = packet.get("message", "")
            self._store_and_show(room, _html_notification(message))
            return

        if ptype == "history":
            messages = packet.get("messages", [])
            if not messages:
                return
            room     = self._current_room or ""
            sep      = _html_history_separator(room)
            existing = self._room_logs.get(room, [])
            history_htmls = [
                _html_broadcast(
                    m.get("sender", "?"),
                    m.get("message", ""),
                    m.get("timestamp", ""),
                    m.get("sender", "") == self._username,
                )
                for m in messages
            ]
            # Prepend history before any live messages already buffered.
            self._room_logs[room] = [sep] + history_htmls + existing
            self._reload_chat()
            return

        if ptype == "room_list":
            self._populate_room_list(packet.get("rooms", []))
            return

        if ptype == "friend_list":
            friends = packet.get("friends", [])
            self._friend_data = friends
            self._populate_friend_list(friends)
            return

        if ptype == "friend_request":
            self._show_friend_request_notif(packet.get("from", "?"))
            return

        # ptype == "user_list" is legacy; the friend_list packet supersedes it.

    # ------------------------------------------------------------------
    # Chat rendering
    # ------------------------------------------------------------------

    def _append_to_chat(self, html: str) -> None:
        room = self._current_room or ""
        if room not in self._room_logs:
            self._room_logs[room] = []
        self._room_logs[room].append(html)
        self._reload_chat()

    def _store_and_show(self, room: str, html: str) -> None:
        if room not in self._room_logs:
            self._room_logs[room] = []
        self._room_logs[room].append(html)

        if room == self._current_room:
            self._reload_chat()
        else:
            self._mark_room_unread(room)

    def _reload_chat(self) -> None:
        if self._current_pm_target:
            parts = self._pm_logs.get(self._current_pm_target, [])
        else:
            parts = self._room_logs.get(self._current_room or "", [])

        self._chat_area.setHtml(
            f'<html><body style="'
            f'background-color:#0d1117;'
            f'margin:6px 4px;'
            f'padding:0;'
            f'font-family:Segoe UI,Arial,sans-serif;'
            f'">'
            f'{"".join(parts)}'
            f'</body></html>'
        )
        QTimer.singleShot(30, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        sb = self._chat_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------
    # Room list helpers
    # ------------------------------------------------------------------

    def _populate_room_list(self, rooms: list[dict]) -> None:
        self._room_list.clear()
        for r in rooms:
            name = r.get("room_name", "")
            self._room_meta[name] = r
            is_locked   = not r.get("is_member") and name not in self._joined_rooms
            lock_suffix = "  🔒" if is_locked else ""
            item = QListWidgetItem(f"  💬  {name}{lock_suffix}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._room_list.addItem(item)
        self._highlight_current_room()

    def _refresh_room_list_ui(self) -> None:
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            meta = self._room_meta.get(name, {})
            if "🔵💬" in item.text():  # keep unread badge if present
                continue
            is_locked   = not meta.get("is_member") and name not in self._joined_rooms
            lock_suffix = "  🔒" if is_locked else ""
            item.setText(f"  💬  {name}{lock_suffix}")
        self._highlight_current_room()

    def _highlight_current_room(self) -> None:
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self._current_room:
                self._room_list.setCurrentItem(item)
                return

    def _mark_room_unread(self, room: str) -> None:
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == room:
                if "🔵" not in item.text():
                    item.setText(f"  🔵💬  {room}")
                return

    # ------------------------------------------------------------------
    # Friend list helpers
    # ------------------------------------------------------------------

    def _populate_friend_list(self, friends: list[dict]) -> None:
        self._user_list.clear()
        for f in friends:
            uname      = f["username"]
            online     = f["online"]
            has_unread = uname in self._pm_logs and uname != self._current_pm_target
            if has_unread:
                icon = "🔵"
            elif online:
                icon = "🟢"
            else:
                icon = "⚫"
            item = QListWidgetItem(f"  {icon}  {uname}")
            item.setData(Qt.ItemDataRole.UserRole, uname)
            item.setData(Qt.ItemDataRole.UserRole + 1, online)
            self._user_list.addItem(item)
        if self._current_pm_target:
            self._highlight_current_user(self._current_pm_target)

    def _highlight_current_user(self, target: str) -> None:
        for i in range(self._user_list.count()):
            item = self._user_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == target:
                self._user_list.setCurrentItem(item)
                return

    def _mark_user_unread(self, username: str) -> None:
        for i in range(self._user_list.count()):
            item = self._user_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == username:
                if "🔵" not in item.text():
                    item.setText(f"  🔵  {username}")
                return

    def _store_pm(self, contact: str, html: str) -> None:
        if contact not in self._pm_logs:
            self._pm_logs[contact] = []
        self._pm_logs[contact].append(html)
        if contact == self._current_pm_target:
            self._reload_chat()

    # ------------------------------------------------------------------
    # Friend request notification bar
    # ------------------------------------------------------------------

    def _show_friend_request_notif(self, from_user: str) -> None:
        self._notif_label.setText(f"👤  Friend request from  {from_user}")

        # Disconnect stale lambdas to avoid one click firing multiple handlers.
        try:
            self._notif_accept_btn.clicked.disconnect()
            self._notif_decline_btn.clicked.disconnect()
        except RuntimeError:
            pass

        self._notif_accept_btn.clicked.connect(
            lambda: self._respond_friend_request(from_user, accept=True)
        )
        self._notif_decline_btn.clicked.connect(
            lambda: self._respond_friend_request(from_user, accept=False)
        )
        self._notif_bar.show()

    def _respond_friend_request(self, from_user: str, accept: bool) -> None:
        if accept:
            self._network.send_accept_friend(from_user)
        else:
            self._network.send_decline_friend(from_user)
        self._notif_bar.hide()

    def _dismiss_notif(self) -> None:
        self._notif_bar.hide()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_send(self) -> None:
        text = self._msg_input.toPlainText().strip()
        if not text:
            return

        if self._current_pm_target:
            self._msg_input.clear()
            self._network.send_private_message(self._current_pm_target, text)
            # Echo own PM locally; the server does not send it back.
            ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self._store_pm(self._current_pm_target, _html_pm_out(text, ts))
        elif self._current_room:
            self._msg_input.clear()
            self._network.send_broadcast(self._current_room, text)
        else:
            self._status_bar.showMessage("✗  Select a room or a user to chat with.", 3000)

    def _on_room_clicked(self, item: QListWidgetItem) -> None:
        room = item.data(Qt.ItemDataRole.UserRole)
        if not room:
            return
        self._current_pm_target = None
        self._user_list.clearSelection()

        meta      = self._room_meta.get(room, {})
        is_member = meta.get("is_member", False) or room in self._joined_rooms

        if not is_member:
            dlg = JoinPasswordDialog(room_name=room, parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            # Optimistically mark as member; server rejects on wrong code.
            self._room_meta.setdefault(room, {})["is_member"] = True
            self._switch_to_room(room, password=dlg.password)
        else:
            self._switch_to_room(room)

    def _switch_to_room(self, room: str, password: str = "") -> None:
        self._current_pm_target = None
        self._current_room      = room
        self._room_name_label.setText(f"#  {room}")
        self._leave_btn.setText("Close Chat")

        self._highlight_current_room()
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == room:
                item.setText(f"  💬  {room}")  # clear unread badge
                break

        self._reload_chat()

        if room not in self._joined_rooms:
            self._network.send_join_room(room, password)
            self._joined_rooms.add(room)
            self._refresh_room_list_ui()

        self._msg_input.setFocus()

    def _switch_to_pm(self, target: str) -> None:
        self._current_pm_target = target
        self._current_room      = None
        self._room_list.clearSelection()
        self._room_name_label.setText(f"💬  {target}")

        # Clear unread badge and restore the correct online/offline icon.
        self._highlight_current_user(target)
        for i in range(self._user_list.count()):
            item = self._user_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == target:
                online = item.data(Qt.ItemDataRole.UserRole + 1)
                icon   = "🟢" if online else "⚫"
                item.setText(f"  {icon}  {target}")
                break

        self._leave_btn.setText("Close Chat")
        self._reload_chat()
        self._msg_input.setFocus()

    def _on_create_room(self) -> None:
        dlg = CreateRoomDialog(parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._network.send_create_room(dlg.room_name)
            # Room list refresh and code display are handled via on_packet (room_code).

    def _on_join_by_code(self) -> None:
        dlg = JoinPasswordDialog(room_name="", parent=self)
        dlg.setWindowTitle("Join a Room")
        if dlg.exec() == dlg.DialogCode.Accepted:
            code = dlg.password.strip().upper()
            if code:
                self._network.send_join_by_code(code)

    def _on_leave_room(self) -> None:
        self._current_pm_target = None
        self._current_room      = None
        self._room_name_label.setText("Select a room →")
        self._leave_btn.setText("Close Chat")
        self._chat_area.clear()
        self._user_list.clearSelection()
        self._room_list.clearSelection()

    def _on_room_context_menu(self, pos) -> None:
        item = self._room_list.itemAt(pos)
        if not item:
            return
        room = item.data(Qt.ItemDataRole.UserRole)
        meta = self._room_meta.get(room, {})
        menu = QMenu(self)

        if meta.get("invite_code"):
            copy_action = menu.addAction("Copy Invite Code")
            copy_action.triggered.connect(lambda: self._copy_invite_code(meta["invite_code"]))

        if meta.get("created_by") == self._username:
            del_action = menu.addAction("Delete Room")
            del_action.triggered.connect(lambda: self._delete_room_action(room))
        else:
            leave_action = menu.addAction("Leave Room")
            leave_action.triggered.connect(lambda: self._leave_room_action(room))

        menu.exec(self._room_list.mapToGlobal(pos))

    def _copy_invite_code(self, code: str) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(code)
        self._status_bar.showMessage(f"✓  Copied invite code: {code}", 3000)

    def _delete_room_action(self, room: str) -> None:
        from PyQt6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self, "Delete Room",
            f"Are you sure you want to permanently delete the room '{room}'?\n"
            f"All messages and members will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._network.send_delete_room(room)
            self._remove_room_from_ui(room)

    def _leave_room_action(self, room: str) -> None:
        self._network.send_leave_room(room)
        self._remove_room_from_ui(room)

    def _remove_room_from_ui(self, room: str) -> None:
        self._joined_rooms.discard(room)
        if self._current_room == room:
            self._current_room = None
            self._room_name_label.setText("Select a room →")
            self._leave_btn.setText("Close Chat")
            self._chat_area.clear()
        self._room_meta.pop(room, None)
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == room:
                self._room_list.takeItem(i)
                break
        self._refresh_room_list_ui()

    def _on_user_clicked(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if not target or target == self._username:
            return
        online = item.data(Qt.ItemDataRole.UserRole + 1)
        if not online:
            self._status_bar.showMessage(f"⚫  {target} is currently offline.", 3000)
            return
        self._switch_to_pm(target)

    def _on_friend_context_menu(self, pos) -> None:
        item = self._user_list.itemAt(pos)
        if not item:
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        online = item.data(Qt.ItemDataRole.UserRole + 1)
        menu   = QMenu(self)
        if online:
            pm_action = menu.addAction("✉️  Send PM")
            pm_action.triggered.connect(lambda: self._switch_to_pm(target))
        remove_action = menu.addAction("🔴  Remove Friend")
        remove_action.triggered.connect(lambda: self._on_remove_friend(target))
        menu.exec(self._user_list.mapToGlobal(pos))

    def _on_add_friend(self) -> None:
        dlg = AddFriendDialog(parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._network.send_add_friend(dlg.username)

    def _on_remove_friend(self, target: str) -> None:
        from PyQt6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self, "Remove Friend",
            f"Remove '{target}' from your friends list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._network.send_remove_friend(target)
            if self._current_pm_target == target:
                self._current_pm_target = None
                self._room_name_label.setText("Select a room →")
                self._leave_btn.setText("Close Chat")
                self._chat_area.clear()

    def _on_refresh(self) -> None:
        self._network.send_get_rooms()
        self._network.send_get_friends()
        self._status_bar.showMessage("Refreshed.", 2000)

    def _on_logout(self) -> None:
        self._logged_out = True
        self._network.send_logout()
        self._network.disconnect()
        self.close()

    def _on_disconnected(self) -> None:
        self._append_to_chat(_html_system("⚠  Disconnected from server.", RED))
        self._status_bar.showMessage("Disconnected from server.")

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Only send logout if the user didn't explicitly click the Logout button.
        if self._network.is_connected and not self._logged_out:
            self._network.send_logout()
            self._network.disconnect()
        event.accept()
