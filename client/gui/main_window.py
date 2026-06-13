import base64
import io
import os
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


from PyQt6.QtCore import QSize, Qt, QTimer, QUrl, pyqtSlot
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QFrame,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidgetAction,
    QWidget,
)

from client.gui.dialogs import (
    AddFriendDialog,
    CreateRoomDialog,
    JoinPasswordDialog,
    RoomCodeDialog,
)
from client.gui.styles import RED
from client.network_client import NetworkClient

MAX_TRANSFER_BYTES = 5 * 1024 * 1024
VOICE_RATE = 16000
VOICE_CHANNELS = 1
VOICE_SAMPLE_WIDTH = 2
VOICE_CHUNK = 1024
VOICE_MAX_SECONDS = 90
REACTION_EMOJIS = ["👍", "❤️", "😂", "🎉", "🔥", "✅"]
MESSAGE_EMOJIS = ["🙂", "😂", "👍", "❤️", "🎉", "🙏", "🔥", "✅"]
APP_TITLE = "Nge-Chat : Multi Chat Room"
LIST_DISPLAY_ROLE = Qt.ItemDataRole.UserRole + 10


def _fmt_ts(timestamp: str) -> str:
    try:
        return timestamp.split(" ")[1][:5]
    except Exception:
        return ""


class _MsgInput(QTextEdit):
    def __init__(self, on_send_callback, parent=None) -> None:
        super().__init__(parent)
        self._on_send = on_send_callback
        self.setObjectName("msg_input")
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setPlaceholderText("Type a message...")
        self.setToolTip("Enter to send, Shift+Enter for newline")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._on_send()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):

    def __init__(self, network: NetworkClient, username: str, password: str = "") -> None:
        super().__init__()
        self._network = network
        self._username = username
        self._password = password
        self._current_room: str | None = None
        self._current_pm_target: str | None = None
        self._joined_rooms: set[str] = set()

        self._room_scrolls: dict[str, QScrollArea] = {}
        self._room_layouts: dict[str, QVBoxLayout] = {}
        self._pm_scrolls: dict[str, QScrollArea] = {}
        self._pm_layouts: dict[str, QVBoxLayout] = {}

        self._room_meta: dict[str, dict] = {}
        self._friend_data: list[dict] = []
        self._online_users: list[str] = []
        self._message_reaction_labels: dict[str, QLabel] = {}
        self._message_reactions: dict[str, list[dict]] = {}
        self._file_payloads: dict[str, dict] = {}
        self._logged_out = False
        self._downloads_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "downloads",
        )
        self._audio_output = QAudioOutput(self)
        self._audio_player = QMediaPlayer(self)
        self._audio_player.setAudioOutput(self._audio_output)
        self._audio_player.positionChanged.connect(self._on_voice_position_changed)
        self._audio_player.durationChanged.connect(self._on_voice_duration_changed)
        self._audio_player.playbackStateChanged.connect(self._on_voice_playback_state_changed)
        self._audio_player.mediaStatusChanged.connect(self._on_voice_media_status_changed)
        self._voice_temp_files: list[str] = []
        self._voice_sliders: dict[str, QSlider] = {}
        self._voice_time_labels: dict[str, QLabel] = {}
        self._voice_play_buttons: dict[str, QPushButton] = {}
        self._voice_durations: dict[str, int] = {}
        self._active_voice_message_id: str | None = None
        self._voice_button: QPushButton | None = None
        self._recording_voice = False
        self._record_frames: list[bytes] = []
        self._record_thread: threading.Thread | None = None
        self._record_stop_event = threading.Event()
        self._record_started_at = 0.0
        self._record_scope: tuple[str, str] | None = None

        self.setWindowTitle(f"{APP_TITLE} - {username}")
        self.setMinimumSize(900, 620)
        self.resize(1100, 700)

        self._setup_ui()
        self._connect_signals()

        QTimer.singleShot(300, self._initial_fetch)
        self._presence_timer = QTimer(self)
        self._presence_timer.setInterval(5000)
        self._presence_timer.timeout.connect(self._poll_presence)
        self._presence_timer.start()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_body(), stretch=1)

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

        title = QLabel(APP_TITLE)
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

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

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
        act_join = add_menu.addAction("🔑  Join with Invite Code")
        act_create.triggered.connect(self._on_create_room)
        act_join.triggered.connect(self._on_join_by_code)
        add_btn.setMenu(add_menu)
        lv.addWidget(add_btn)

        chat_frame = QFrame()
        chat_frame.setObjectName("chat_frame")
        chat_frame.setMinimumWidth(350)
        cv = QVBoxLayout(chat_frame)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        self._chat_header_bar = QFrame()
        self._chat_header_bar.setObjectName("chat_header_bar")
        self._chat_header_bar.setFixedHeight(48)
        chh = QHBoxLayout(self._chat_header_bar)
        chh.setContentsMargins(14, 0, 14, 0)
        chh.setSpacing(10)

        chh.addStretch()
        self._room_name_label = QLabel("Select a room →")
        self._room_name_label.setObjectName("chat_room_name")
        self._room_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        chh.addWidget(self._room_name_label)
        chh.addStretch()

        self._leave_btn = QPushButton("Leave Room")
        self._leave_btn.setObjectName("danger_btn")
        self._leave_btn.setFixedHeight(28)
        self._leave_btn.clicked.connect(self._on_leave_room)
        chh.addWidget(self._leave_btn)

        cv.addWidget(self._chat_header_bar)
        self._chat_header_bar.hide()

        self._chat_stack = QStackedWidget()
        cv.addWidget(self._chat_stack, stretch=1)

        empty_page = QWidget()
        empty_page.setStyleSheet("background-color: transparent;")
        self._chat_stack.addWidget(empty_page)
        self._chat_stack.setCurrentWidget(empty_page)

        self._input_bar = self._build_input_bar()
        cv.addWidget(self._input_bar)
        self._input_bar.hide()

        right = QFrame()
        right.setObjectName("right_panel")
        right.setMinimumWidth(190)
        right.setMaximumWidth(260)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 10)
        rv.setSpacing(0)

        online_hdr = QLabel("ONLINE USERS")
        online_hdr.setObjectName("section_header")
        rv.addWidget(online_hdr)

        self._online_list = QListWidget()
        self._online_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._online_list.itemClicked.connect(self._on_online_user_clicked)
        self._online_list.itemDoubleClicked.connect(self._on_online_user_clicked)
        self._online_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._online_list.customContextMenuRequested.connect(
            self._on_online_context_menu
        )
        rv.addWidget(self._online_list, stretch=1)

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

        self._pending_req_btn = QPushButton("📩 Friend Requests")
        self._pending_req_btn.setFixedHeight(34)
        self._pending_req_btn.setStyleSheet("margin: 6px 10px; border-radius: 6px;")
        self._pending_req_btn.clicked.connect(self._on_view_friend_requests)
        rv.addWidget(self._pending_req_btn)

        add_friend_btn = QPushButton("➕  Add Friend")
        add_friend_btn.setObjectName("accent_btn")
        add_friend_btn.setFixedHeight(34)
        add_friend_btn.setStyleSheet("margin: 6px 10px; border-radius: 6px;")
        add_friend_btn.clicked.connect(self._on_add_friend)
        rv.addWidget(add_friend_btn)

        splitter.addWidget(left)
        splitter.addWidget(chat_frame)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)

        return splitter

    def _build_input_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("chat_input_bar")
        bar.setFixedHeight(112)
        v = QVBoxLayout(bar)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        self._msg_input = _MsgInput(on_send_callback=self._on_send)
        v.addWidget(self._msg_input)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)

        emoji_btn = QPushButton("🙂")
        emoji_btn.setObjectName("input_action_btn")
        emoji_btn.setFixedSize(44, 36)
        emoji_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        emoji_btn.setToolTip("Insert an emoji into your message")
        emoji_btn.clicked.connect(
            lambda checked=False, anchor=emoji_btn: self._show_emoji_picker(anchor)
        )
        actions.addWidget(emoji_btn)

        file_btn = QPushButton("File")
        file_btn.setObjectName("input_action_btn")
        file_btn.setFixedSize(56, 36)
        file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        file_btn.setToolTip("Send a file to the active room or private chat")
        file_btn.clicked.connect(self._on_send_file)
        actions.addWidget(file_btn)

        voice_btn = QPushButton("Voice")
        voice_btn.setObjectName("input_action_btn")
        voice_btn.setFixedSize(66, 36)
        voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        voice_btn.setToolTip("Record and send a voice message")
        voice_btn.clicked.connect(self._on_send_voice)
        actions.addWidget(voice_btn)
        self._voice_button = voice_btn

        send_btn = QPushButton("Send")
        send_btn.setObjectName("chat_send_btn")
        send_btn.setFixedSize(96, 36)
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.clicked.connect(self._on_send)
        actions.addWidget(send_btn)

        v.addLayout(actions)

        return bar

    def _connect_signals(self) -> None:
        self._network.packet_received.connect(self.on_packet)
        self._network.disconnected_signal.connect(self._on_disconnected)

    def _initial_fetch(self) -> None:
        self._network.send_get_rooms()
        self._network.send_get_users()
        self._network.send_get_friends()

    def _poll_presence(self) -> None:
        if self._network.is_connected:
            self._network.send_get_users()
            self._network.send_get_friends()

    @pyqtSlot(dict)
    def on_packet(self, packet: dict) -> None:
        ptype = packet.get("type")
        status = packet.get("status")

        if status == "ok":
            msg = packet.get("message", "")
            room_code = packet.get("room_code")
            room_name = packet.get("room_name", "")

            if room_code:
                dlg = RoomCodeDialog(room_name=room_name, code=room_code, parent=self)
                dlg.exec()
                QTimer.singleShot(300, self._network.send_get_rooms)
                QTimer.singleShot(600, lambda rn=room_name: self._switch_to_room(rn))
            elif room_name and "Joined room" in msg:
                meta = self._room_meta.get(room_name, {})
                meta["is_member"] = True
                self._room_meta[room_name] = meta
                self._joined_rooms.add(room_name)
                QTimer.singleShot(300, self._network.send_get_rooms)
                QTimer.singleShot(600, lambda rn=room_name: self._switch_to_room(rn))
            else:
                self._status_bar.showMessage(f"✓  {msg}", 4000)

            if "Joined room" in msg and not room_name:
                room = msg.split("'")[1] if "'" in msg else self._current_room
                if room:
                    self._joined_rooms.add(room)
                    self._refresh_room_list_ui()
            return

        if status == "error":
            msg = packet.get("message", "Error")
            self._status_bar.showMessage(f"✗  {msg}", 5000)
            if self._current_room:
                self._add_chat_bubble(
                    self._current_room, False, {"type": "system", "message": f"✗  {msg}", "color": "#EF4444"}
                )
            if msg == "Wrong invite code." and self._current_room:
                self._joined_rooms.discard(self._current_room)
                self._room_meta.setdefault(self._current_room, {})["is_member"] = False
                self._current_room = None
                self._room_name_label.setText("Select a room →")
                self._leave_btn.setText("Close Chat")
                self._refresh_room_list_ui()
                self._chat_header_bar.hide()
                self._input_bar.hide()
            return

        if ptype == "broadcast":
            room = packet.get("room") or packet.get("room_name")
            if not room:
                return

            data = {
                "type": "broadcast",
                "message_id": packet.get("message_id", ""),
                "sender": packet.get("sender", "?"),
                "message": packet.get("message", ""),
                "timestamp": packet.get("timestamp", ""),
                "is_own": packet.get("sender", "") == self._username,
                "reactions": packet.get("reactions", []),
            }
            self._add_chat_bubble(room, False, data)
            return

        if ptype == "private_message":
            sender = packet.get("sender")
            target = packet.get("target", "")
            msg = packet.get("message", "")
            ts = packet.get("timestamp", "")
            if not sender:
                return
            chat_target = target if sender == self._username else sender

            data = {
                "type": "pm",
                "message_id": packet.get("message_id", ""),
                "sender": sender,
                "message": msg,
                "timestamp": ts,
                "is_own": sender == self._username,
                "is_pm": True,
                "reactions": packet.get("reactions", []),
            }
            self._add_chat_bubble(chat_target, True, data)
            return

        if ptype == "file_transfer":
            scope = packet.get("scope", "")
            sender = packet.get("sender", "?")
            is_pm = scope == "private"
            target = packet.get("room", "") if not is_pm else sender
            if is_pm and sender == self._username:
                target = packet.get("target", "")
            if not target:
                return

            message_id = packet.get("message_id", "")
            if message_id:
                self._file_payloads[message_id] = {
                    "filename": packet.get("filename", "attachment.bin"),
                    "data": packet.get("data", ""),
                    "kind": packet.get("kind", "file"),
                }

            data = {
                "type": "file",
                "message_id": message_id,
                "sender": sender,
                "filename": packet.get("filename", "attachment.bin"),
                "timestamp": packet.get("timestamp", ""),
                "size": packet.get("size", 0),
                "kind": packet.get("kind", "file"),
                "is_own": sender == self._username,
                "is_pm": is_pm,
                "reactions": packet.get("reactions", []),
                "download_available": bool(packet.get("data", "")),
            }
            self._add_chat_bubble(target, is_pm, data)
            return

        if ptype == "reaction":
            self._set_message_reactions(
                packet.get("message_id", ""), packet.get("reactions", [])
            )
            return

        if ptype == "notification":
            room = packet.get("room", "")
            message = packet.get("message", "")
            if room:
                self._add_chat_bubble(
                    room, False, {"type": "notification", "message": message}
                )
            return

        if ptype == "history":
            messages = packet.get("messages", [])
            room = packet.get("room", "") or self._current_room
            if not room:
                return

            scroll, layout = self._get_or_create_chat(room, False)

            # Clear existing widgets (except the stretch at the end)
            while layout.count() > 1:
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            last_date = ""
            for m in messages:
                ts = m.get("timestamp", "")
                date_str = ts.split(" ")[0] if ts else "History"
                if date_str != last_date:
                    layout.insertWidget(
                        layout.count() - 1,
                        self._create_bubble_widget(
                            {"type": "date_separator", "date": date_str}
                        ),
                    )
                    last_date = date_str

                data = self._history_message_to_bubble_data(m, is_pm=False)
                layout.insertWidget(
                    layout.count() - 1, self._create_bubble_widget(data)
                )

            if room == self._current_room:
                self._chat_stack.setCurrentWidget(scroll)
                QTimer.singleShot(
                    30,
                    lambda: scroll.verticalScrollBar().setValue(
                        scroll.verticalScrollBar().maximum()
                    ),
                )
            return

        if ptype == "pm_history":
            messages = packet.get("messages", [])
            target = packet.get("target", "")
            if not target:
                return

            scroll, layout = self._get_or_create_chat(target, True)

            while layout.count() > 1:
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            last_date = ""
            for m in messages:
                ts = m.get("timestamp", "")
                date_str = ts.split(" ")[0] if ts else "History"
                if date_str != last_date:
                    layout.insertWidget(
                        layout.count() - 1,
                        self._create_bubble_widget(
                            {"type": "date_separator", "date": date_str}
                        ),
                    )
                    last_date = date_str

                data = self._history_message_to_bubble_data(m, is_pm=True)
                layout.insertWidget(
                    layout.count() - 1, self._create_bubble_widget(data)
                )

            if target == self._current_pm_target:
                self._chat_stack.setCurrentWidget(scroll)
                QTimer.singleShot(
                    30,
                    lambda: scroll.verticalScrollBar().setValue(
                        scroll.verticalScrollBar().maximum()
                    ),
                )
            return

        if ptype == "room_list":
            self._populate_room_list(packet.get("rooms", []))
            return

        if ptype == "user_list":
            self._populate_online_list(packet.get("users", []))
            return

        if ptype == "friend_list":
            friends = packet.get("friends", [])
            self._friend_data = friends
            self._populate_friend_list(friends)
            return

        if ptype == "friend_request":
            self._show_friend_request_notif(packet.get("from", "?"))
            return

        if ptype == "pending_requests_list":
            requests = packet.get("requests", [])
            self._show_friend_requests_dialog(requests)
            return

        pass

    def _history_message_to_bubble_data(self, message: dict, is_pm: bool) -> dict:
        attachment = message.get("attachment")
        message_id = message.get("message_id", "")
        if attachment:
            if message_id:
                self._file_payloads[message_id] = {
                    "filename": attachment.get("filename", "attachment.bin"),
                    "data": attachment.get("data", ""),
                    "kind": attachment.get("kind", "file"),
                }
            return {
                "type": "file",
                "message_id": message_id,
                "sender": message.get("sender", "?"),
                "filename": attachment.get("filename", "attachment.bin"),
                "timestamp": message.get("timestamp", ""),
                "size": attachment.get("size", 0),
                "kind": attachment.get("kind", "file"),
                "is_own": message.get("sender", "") == self._username,
                "is_pm": is_pm,
                "reactions": message.get("reactions", []),
                "download_available": bool(attachment.get("data", "")),
            }

        body = message.get("message", "")
        legacy_prefixes = (
            ("[File] ", "file"),
            ("[Voice] ", "voice"),
            ("Voice note: ", "voice"),
        )
        for prefix, kind in legacy_prefixes:
            if isinstance(body, str) and body.startswith(prefix):
                filename = body.replace(prefix, "", 1).strip() or "attachment.bin"
                return {
                    "type": "file",
                    "message_id": message_id,
                    "sender": message.get("sender", "?"),
                    "filename": filename,
                    "timestamp": message.get("timestamp", ""),
                    "size": 0,
                    "kind": kind,
                    "is_own": message.get("sender", "") == self._username,
                    "is_pm": is_pm,
                    "reactions": message.get("reactions", []),
                    "download_available": False,
                }

        return {
            "type": "pm" if is_pm else "broadcast",
            "message_id": message_id,
            "sender": message.get("sender", "?"),
            "message": message.get("message", ""),
            "timestamp": message.get("timestamp", ""),
            "is_own": message.get("sender", "") == self._username,
            "is_pm": is_pm,
            "reactions": message.get("reactions", []),
        }

    @staticmethod
    def _format_size(size: int) -> str:
        if size <= 0:
            return "unknown size"
        units = ["B", "KB", "MB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = os.path.basename(filename).strip().replace("\x00", "")
        cleaned = []
        for ch in name:
            if ch.isalnum() or ch in (" ", ".", "_", "-"):
                cleaned.append(ch)
            else:
                cleaned.append("_")
        safe = "".join(cleaned).strip(" .")
        return safe[:120] or "attachment.bin"

    def _decode_payload(self, message_id: str) -> tuple[str, str, bytes] | None:
        payload = self._file_payloads.get(message_id)
        if not payload:
            self._status_bar.showMessage("Attachment data is not available.", 4000)
            return None
        try:
            raw = base64.b64decode(payload.get("data", ""), validate=True)
        except Exception:
            self._status_bar.showMessage("Attachment data is invalid.", 4000)
            return None
        return (
            self._safe_filename(payload.get("filename", "attachment.bin")),
            payload.get("kind", "file"),
            raw,
        )

    def _download_file_payload(self, message_id: str) -> None:
        decoded = self._decode_payload(message_id)
        if decoded is None:
            return
        filename, _kind, raw = decoded
        os.makedirs(self._downloads_dir, exist_ok=True)
        default_path = os.path.join(self._downloads_dir, filename)
        path, _ = QFileDialog.getSaveFileName(self, "Save attachment", default_path)
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(raw)
            self._status_bar.showMessage(f"Downloaded: {path}", 5000)
        except OSError as exc:
            QMessageBox.warning(self, "Download Failed", str(exc))

    def _play_voice_payload(self, message_id: str) -> None:
        if (
            self._active_voice_message_id == message_id
            and self._audio_player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._audio_player.pause()
            return

        if (
            self._active_voice_message_id == message_id
            and self._audio_player.playbackState()
            == QMediaPlayer.PlaybackState.PausedState
        ):
            self._audio_player.play()
            return

        decoded = self._decode_payload(message_id)
        if decoded is None:
            return
        filename, _kind, raw = decoded
        suffix = os.path.splitext(filename)[1] or ".wav"
        try:
            temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            temp.write(raw)
            temp.close()
        except OSError as exc:
            QMessageBox.warning(self, "Playback Failed", str(exc))
            return

        self._voice_temp_files.append(temp.name)
        if self._active_voice_message_id and self._active_voice_message_id != message_id:
            previous = self._voice_play_buttons.get(self._active_voice_message_id)
            if previous:
                previous.setText("Play")
        self._active_voice_message_id = message_id
        self._set_voice_progress(message_id, 0, self._voice_durations.get(message_id, 0))
        self._audio_player.stop()
        self._audio_player.setSource(QUrl.fromLocalFile(temp.name))
        self._audio_player.play()

    @staticmethod
    def _format_audio_ms(milliseconds: int) -> str:
        total_seconds = max(0, int(milliseconds / 1000))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _voice_progress_text(self, position_ms: int, duration_ms: int) -> str:
        duration_text = self._format_audio_ms(duration_ms) if duration_ms else "--:--"
        return f"{self._format_audio_ms(position_ms)} / {duration_text}"

    def _estimate_voice_duration_ms(self, message_id: str) -> int:
        payload = self._file_payloads.get(message_id)
        if not payload:
            return 0
        try:
            raw = base64.b64decode(payload.get("data", ""), validate=True)
            with wave.open(io.BytesIO(raw), "rb") as wav:
                frame_count = wav.getnframes()
                frame_rate = wav.getframerate()
                if frame_rate <= 0:
                    return 0
                return int((frame_count / frame_rate) * 1000)
        except Exception:
            return 0

    def _set_voice_progress(
        self, message_id: str, position_ms: int, duration_ms: int
    ) -> None:
        if duration_ms:
            self._voice_durations[message_id] = duration_ms
        duration_ms = duration_ms or self._voice_durations.get(message_id, 0)

        slider = self._voice_sliders.get(message_id)
        if slider:
            if duration_ms:
                slider.setRange(0, duration_ms)
            if not slider.isSliderDown():
                slider.setValue(min(position_ms, slider.maximum()))

        label = self._voice_time_labels.get(message_id)
        if label:
            label.setText(self._voice_progress_text(position_ms, duration_ms))

    def _preview_voice_position(self, message_id: str, position_ms: int) -> None:
        duration_ms = self._voice_durations.get(message_id, 0)
        label = self._voice_time_labels.get(message_id)
        if label:
            label.setText(self._voice_progress_text(position_ms, duration_ms))

    def _seek_voice_to_slider(self, message_id: str, slider: QSlider) -> None:
        if self._active_voice_message_id == message_id:
            self._audio_player.setPosition(slider.value())
        self._set_voice_progress(
            message_id, slider.value(), self._voice_durations.get(message_id, 0)
        )

    def _on_voice_position_changed(self, position_ms: int) -> None:
        if not self._active_voice_message_id:
            return
        self._set_voice_progress(
            self._active_voice_message_id,
            position_ms,
            self._voice_durations.get(self._active_voice_message_id, 0),
        )

    def _on_voice_duration_changed(self, duration_ms: int) -> None:
        if not self._active_voice_message_id or duration_ms <= 0:
            return
        self._set_voice_progress(
            self._active_voice_message_id,
            self._audio_player.position(),
            duration_ms,
        )

    def _on_voice_playback_state_changed(self, state) -> None:
        message_id = self._active_voice_message_id
        if not message_id:
            return
        btn = self._voice_play_buttons.get(message_id)
        if not btn:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            btn.setText("Pause")
        else:
            btn.setText("Play")

    def _on_voice_media_status_changed(self, status) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        message_id = self._active_voice_message_id
        if not message_id:
            return
        duration = self._voice_durations.get(message_id, self._audio_player.duration())
        self._set_voice_progress(message_id, duration, duration)
        btn = self._voice_play_buttons.get(message_id)
        if btn:
            btn.setText("Play")
        self._active_voice_message_id = None

    def _get_or_create_chat(self, target: str, is_pm: bool):
        scrolls = self._pm_scrolls if is_pm else self._room_scrolls
        layouts = self._pm_layouts if is_pm else self._room_layouts

        if target in scrolls:
            return scrolls[target], layouts[target]

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background-color: transparent; }"
        )

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()

        scroll.setWidget(container)
        scrolls[target] = scroll
        layouts[target] = layout

        self._chat_stack.addWidget(scroll)
        return scroll, layout

    def _add_chat_bubble(self, target: str, is_pm: bool, data: dict) -> None:
        scroll, layout = self._get_or_create_chat(target, is_pm)
        widget = self._create_bubble_widget(data)
        layout.insertWidget(layout.count() - 1, widget)

        if (is_pm and target == self._current_pm_target) or (
            not is_pm and target == self._current_room
        ):
            self._chat_stack.setCurrentWidget(scroll)
            QTimer.singleShot(
                30,
                lambda: scroll.verticalScrollBar().setValue(
                    scroll.verticalScrollBar().maximum()
                ),
            )
        elif not is_pm:
            self._mark_room_unread(target)
        elif is_pm:
            self._mark_user_unread(target)

    def _create_bubble_widget(self, p: dict) -> QWidget:
        ptype = p.get("type")
        msg = p.get("message", "")
        ts = _fmt_ts(p.get("timestamp", ""))

        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(12, 4, 12, 4)

        if ptype == "system":
            lbl = QLabel(msg)
            lbl.setStyleSheet(
                f"color: {p.get('color', '#94A3B8')}; font-size: 13px; font-weight: 500;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(lbl)
            return container

        if ptype == "date_separator":
            lbl = QLabel(f"●  {p.get('date')}  ●")
            lbl.setStyleSheet(
                "color: #64748B; font-size: 12px; font-weight: bold; background-color: #1E293B; border-radius: 12px; padding: 4px 12px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(lbl)
            return container

        if ptype == "notification":
            lbl = QLabel(msg)
            lbl.setStyleSheet(
                "color: #94A3B8; font-size: 12px; font-style: italic; background-color: #1E293B; border-radius: 12px; padding: 4px 12px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(lbl)
            return container

        if ptype == "reaction":
            sender = p.get("sender", "")
            emoji = p.get("emoji", "")
            prefix = "You reacted" if p.get("is_own", False) else f"{sender} reacted"
            lbl = QLabel(f"{prefix} {emoji}")
            lbl.setStyleSheet(
                "color: #FDE68A; font-size: 13px; font-weight: 700; "
                "background-color: #3B2F11; border: 1px solid #92400E; "
                "border-radius: 12px; padding: 5px 12px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addStretch(1)
            row.addWidget(lbl)
            row.addStretch(1)
            return container

        if ptype == "file":
            is_own = p.get("is_own", False)
            sender = p.get("sender", "")
            filename = p.get("filename", "attachment.bin")
            kind = p.get("kind", "file")
            message_id = p.get("message_id", "")
            size = int(p.get("size") or 0)
            has_payload = bool(p.get("download_available", message_id in self._file_payloads))
            size_text = self._format_size(size) if size > 0 else "not available locally"
            title = "Voice note" if kind == "voice" else "File"
            reaction_widgets = []

            bubble = QFrame()
            bubble.setObjectName("chat_bubble")
            bubble.setMinimumWidth(360 if kind == "voice" else 300)
            bubble.setMaximumWidth(520 if kind == "voice" else 430)
            blayout = QVBoxLayout(bubble)
            blayout.setContentsMargins(16, 12, 16, 10)
            blayout.setSpacing(7)
            reaction_widgets.append(bubble)

            if not is_own and sender:
                s_lbl = QLabel(sender + (" (private)" if p.get("is_pm") else ""))
                s_lbl.setStyleSheet("color: #2DD4BF; font-weight: bold; font-size: 12px;")
                blayout.addWidget(s_lbl)
                reaction_widgets.append(s_lbl)

            type_lbl = QLabel(title.upper())
            type_lbl.setStyleSheet(
                "color: #BAE6FD; font-size: 10px; font-weight: 800; "
                "letter-spacing: 0.8px; background: transparent;"
            )
            blayout.addWidget(type_lbl)

            file_lbl = QLabel(filename)
            file_lbl.setWordWrap(True)
            file_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            file_lbl.setStyleSheet(
                "color: #F8FAFC; font-size: 14px; font-weight: 800; background: transparent;"
            )
            blayout.addWidget(file_lbl)
            reaction_widgets.append(type_lbl)
            reaction_widgets.append(file_lbl)

            detail_lbl = QLabel(size_text)
            detail_lbl.setWordWrap(True)
            detail_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail_lbl.setStyleSheet(
                "color: #D8F3FF; font-size: 11px; background: transparent;"
            )
            blayout.addWidget(detail_lbl)
            reaction_widgets.append(detail_lbl)

            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            action_button_style = """
                QPushButton {
                    background-color: #F8FAFC;
                    color: #0F172A;
                    border: none;
                    border-radius: 8px;
                    padding: 7px 14px;
                    font-size: 12px;
                    font-weight: 800;
                }
                QPushButton:hover { background-color: #E0F2FE; }
                QPushButton:disabled {
                    background-color: rgba(148, 163, 184, 0.28);
                    color: rgba(248, 250, 252, 0.55);
                }
            """
            if kind == "voice":
                duration_ms = (
                    self._estimate_voice_duration_ms(message_id) if has_payload else 0
                )
                if duration_ms:
                    self._voice_durations[message_id] = duration_ms

                play_btn = QPushButton("Play")
                play_btn.setFixedWidth(74)
                play_btn.setFixedHeight(34)
                play_btn.setStyleSheet(action_button_style)
                play_btn.setEnabled(has_payload)
                play_btn.setToolTip(
                    "Play this voice message"
                    if has_payload
                    else "Voice payload is not available in history."
                )
                play_btn.clicked.connect(
                    lambda checked=False, mid=message_id: self._play_voice_payload(mid)
                )
                self._voice_play_buttons[message_id] = play_btn
                action_row.addWidget(play_btn)

                progress = QSlider(Qt.Orientation.Horizontal)
                progress.setRange(0, duration_ms or 1000)
                progress.setValue(0)
                progress.setEnabled(has_payload)
                progress.setMinimumWidth(170)
                progress.setStyleSheet(
                    """
                    QSlider::groove:horizontal {
                        height: 7px;
                        border-radius: 3px;
                        background: rgba(248, 250, 252, 0.28);
                    }
                    QSlider::sub-page:horizontal {
                        background: #F8FAFC;
                        border-radius: 3px;
                    }
                    QSlider::add-page:horizontal {
                        background: rgba(248, 250, 252, 0.28);
                        border-radius: 3px;
                    }
                    QSlider::handle:horizontal {
                        width: 14px;
                        height: 14px;
                        margin: -4px 0;
                        border-radius: 7px;
                        background: #F8FAFC;
                    }
                    QSlider::groove:horizontal:disabled {
                        background: rgba(148, 163, 184, 0.22);
                    }
                    QSlider::add-page:horizontal:disabled {
                        background: rgba(148, 163, 184, 0.22);
                    }
                    QSlider::handle:horizontal:disabled {
                        background: rgba(248, 250, 252, 0.45);
                    }
                    """
                )
                progress.sliderMoved.connect(
                    lambda value, mid=message_id: self._preview_voice_position(mid, value)
                )
                progress.sliderReleased.connect(
                    lambda mid=message_id, slider=progress: self._seek_voice_to_slider(
                        mid, slider
                    )
                )
                self._voice_sliders[message_id] = progress
                action_row.addWidget(progress, stretch=1)

                time_lbl = QLabel(self._voice_progress_text(0, duration_ms))
                time_lbl.setFixedWidth(76)
                time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                time_lbl.setStyleSheet(
                    "color: #E0F2FE; font-size: 11px; font-weight: 700; background: transparent;"
                )
                self._voice_time_labels[message_id] = time_lbl
                action_row.addWidget(time_lbl)
            else:
                download_btn = QPushButton("Download")
                download_btn.setFixedWidth(118)
                download_btn.setFixedHeight(34)
                download_btn.setStyleSheet(action_button_style)
                download_btn.setEnabled(has_payload)
                download_btn.setToolTip(
                    "Choose where to save this file"
                    if has_payload
                    else "File payload is not available for this older message."
                )
                download_btn.clicked.connect(
                    lambda checked=False, mid=message_id: self._download_file_payload(mid)
                )
                action_row.addWidget(download_btn)
                action_row.addStretch(1)
            blayout.addLayout(action_row)

            footer = QHBoxLayout()
            footer.addStretch(1)
            ts_lbl = QLabel(ts)
            ts_lbl.setStyleSheet("color: #A5B4FC; font-size: 10px; background: transparent;")
            ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            footer.addWidget(ts_lbl)
            blayout.addLayout(footer)
            self._add_reaction_label(
                blayout, message_id, p.get("reactions", [])
            )
            self._attach_reaction_menu(
                reaction_widgets, message_id, p.get("is_pm", False)
            )

            bg = "#0E7490" if kind == "voice" else ("#2563EB" if is_own else "#155E75")
            bubble.setStyleSheet(
                f"#chat_bubble {{ background-color: {bg}; border-radius: 14px; }}"
            )
            if is_own:
                row.addStretch(1)
                row.addWidget(bubble)
                row.addSpacing(20)
            else:
                row.addSpacing(20)
                row.addWidget(bubble)
                row.addStretch(1)
            return container

        is_own = p.get("is_own", False)
        sender = p.get("sender", "")
        is_pm = p.get("is_pm", False)

        bubble = QFrame()
        bubble.setMaximumWidth(520)
        blayout = QVBoxLayout(bubble)
        blayout.setContentsMargins(14, 10, 14, 8)
        blayout.setSpacing(6)
        reaction_widgets = [bubble]

        if not is_own and sender:
            s_lbl = QLabel(sender + (" (private)" if is_pm else ""))
            color = "#C4B5FD" if is_pm else "#6366F1"
            s_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            blayout.addWidget(s_lbl)
            reaction_widgets.append(s_lbl)

        msg_lbl = QLabel(msg.replace("&", "&&"))
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            "color: #F8FAFC; font-size: 14px; line-height: 1.35; background-color: transparent;"
        )
        msg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        blayout.addWidget(msg_lbl)
        reaction_widgets.append(msg_lbl)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        ts_lbl = QLabel(ts)
        color = "#C4B5FD" if is_pm else ("#A5B4FC" if is_own else "#94A3B8")
        ts_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background-color: transparent;"
        )
        ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer.addWidget(ts_lbl)
        blayout.addLayout(footer)
        self._add_reaction_label(
            blayout, p.get("message_id", ""), p.get("reactions", [])
        )
        self._attach_reaction_menu(reaction_widgets, p.get("message_id", ""), is_pm)

        bubble.setObjectName("chat_bubble")

        if is_own:
            bg = "#0369A1" if is_pm else "#4F46E5"
            bubble.setStyleSheet(
                f"#chat_bubble {{ background-color: {bg}; border-radius: 16px; border-top-right-radius: 4px; }}"
            )
            row.addStretch(1)
            row.addWidget(bubble)
            row.addSpacing(20)
        else:
            bg = "#0F766E" if is_pm else "#1E293B"
            b_style = f"#chat_bubble {{ background-color: {bg}; border-radius: 16px; border-top-left-radius: 4px;"
            if is_pm:
                b_style += " border-left: 4px solid #2DD4BF;"
            b_style += " }"
            bubble.setStyleSheet(b_style)
            row.addSpacing(20)
            row.addWidget(bubble)
            row.addStretch(1)

        return container

    def _attach_reaction_menu(
        self, widgets: list[QWidget], message_id: str, is_pm: bool
    ) -> None:
        if not message_id:
            return
        for widget in widgets:
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.setToolTip("Right-click to react")
            widget.customContextMenuRequested.connect(
                lambda pos, source=widget, mid=message_id, pm=is_pm: self._show_reaction_menu(
                    source, pos, mid, pm
                )
            )

    def _show_reaction_menu(
        self, source: QWidget, pos, message_id: str, is_pm: bool
    ) -> None:
        if not message_id:
            return
        current_reaction = self._current_user_reaction(message_id)

        def pick_reaction(emoji: str) -> None:
            if emoji == current_reaction:
                self._remove_reaction_for_message(message_id, is_pm)
            else:
                self._send_reaction_for_message(message_id, emoji, is_pm)

        menu = self._build_emoji_panel_menu(
            parent=source,
            emojis=REACTION_EMOJIS,
            title="React to message",
            current_emoji=current_reaction,
            on_pick=pick_reaction,
            on_remove=lambda: self._remove_reaction_for_message(message_id, is_pm),
            remove_enabled=bool(current_reaction),
        )
        menu.exec(source.mapToGlobal(pos))

    def _show_emoji_picker(self, anchor: QPushButton) -> None:
        menu = self._build_emoji_panel_menu(
            parent=anchor,
            emojis=MESSAGE_EMOJIS,
            title="Insert emoji",
            on_pick=self._insert_emoji,
        )
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _build_emoji_panel_menu(
        self,
        *,
        parent: QWidget,
        emojis: list[str],
        title: str,
        on_pick,
        current_emoji: str = "",
        on_remove=None,
        remove_enabled: bool = False,
    ) -> QMenu:
        menu = QMenu(parent)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #111827;
                border: 1px solid #475569;
                border-radius: 12px;
                padding: 0;
            }
            """
        )

        panel = QWidget(menu)
        panel.setFixedWidth(196)
        panel.setStyleSheet("background-color: #111827; border-radius: 12px;")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(10, 9, 10, 10)
        outer.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "color: #CBD5E1; font-size: 11px; font-weight: 800; "
            "letter-spacing: 0.8px; background: transparent;"
        )
        outer.addWidget(title_lbl)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        def choose(emoji: str) -> None:
            menu.close()
            on_pick(emoji)

        for idx, emoji in enumerate(emojis):
            btn = QPushButton(emoji)
            btn.setFixedSize(38, 36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            selected = emoji == current_emoji
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: %s;
                    color: #F8FAFC;
                    border: 1px solid %s;
                    border-radius: 9px;
                    padding: 0;
                    font-size: 18px;
                    font-weight: 700;
                }
                QPushButton:hover {
                    background-color: #334155;
                    border-color: #93C5FD;
                }
                """
                % (
                    "#312E81" if selected else "#1E293B",
                    "#A5B4FC" if selected else "#334155",
                )
            )
            btn.clicked.connect(lambda checked=False, e=emoji: choose(e))
            grid.addWidget(btn, idx // 4, idx % 4)

        outer.addLayout(grid)

        if on_remove is not None:
            remove_btn = QPushButton("Remove reaction")
            remove_btn.setEnabled(remove_enabled)
            remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: transparent;
                    color: #FCA5A5;
                    border: 1px solid #7F1D1D;
                    border-radius: 8px;
                    padding: 7px 10px;
                    font-size: 12px;
                    font-weight: 800;
                }
                QPushButton:hover {
                    background-color: #7F1D1D;
                    color: #F8FAFC;
                }
                QPushButton:disabled {
                    color: #64748B;
                    border-color: #334155;
                    background-color: transparent;
                }
                """
            )

            def remove() -> None:
                menu.close()
                on_remove()

            remove_btn.clicked.connect(remove)
            outer.addWidget(remove_btn)

        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        return menu

    def _add_reaction_label(
        self, layout: QVBoxLayout, message_id: str, reactions: list[dict]
    ) -> None:
        if not message_id:
            return
        lbl = QLabel("")
        lbl.setStyleSheet(
            "color: #FDE68A; font-size: 12px; font-weight: 700; "
            "background-color: rgba(59, 47, 17, 0.55); border-radius: 10px; "
            "padding: 3px 8px;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._message_reaction_labels[message_id] = lbl
        layout.addWidget(lbl)
        self._set_message_reactions(message_id, reactions)

    def _set_message_reactions(self, message_id: str, reactions: list[dict]) -> None:
        if not message_id:
            return
        self._message_reactions[message_id] = reactions
        label = self._message_reaction_labels.get(message_id)
        if not label:
            return

        counts: dict[str, int] = {}
        for reaction in reactions:
            emoji = reaction.get("emoji", "")
            if emoji:
                counts[emoji] = counts.get(emoji, 0) + 1

        if not counts:
            label.hide()
            return

        parts = [f"{emoji} {count}" for emoji, count in counts.items()]
        label.setText("  ".join(parts))
        label.show()

    def _populate_room_list(self, rooms: list[dict]) -> None:
        self._room_list.clear()
        for r in rooms:
            name = r.get("room_name", "")
            self._room_meta[name] = r
            is_locked = not r.get("is_member") and name not in self._joined_rooms
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
            if "🔵💬" in item.text():
                continue
            is_locked = not meta.get("is_member") and name not in self._joined_rooms
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

    def _populate_online_list(self, users: list[str]) -> None:
        self._online_users = sorted(users)
        self._online_list.clear()
        for uname in self._online_users:
            label = f"  🟢  {uname}"
            if uname == self._username:
                label += " (you)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, uname)
            self._online_list.addItem(item)

    def _populate_friend_list(self, friends: list[dict]) -> None:
        self._user_list.clear()
        for f in friends:
            uname = f["username"]
            online = f["online"]
            has_unread = (
                uname in self._pm_layouts
                and self._pm_layouts[uname].count() > 1
                and uname != self._current_pm_target
            )
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

    def _show_friend_request_notif(self, from_user: str) -> None:
        self._pending_req_btn.setText("📩 Friend Requests (New)")
        self._pending_req_btn.setStyleSheet(
            "margin: 6px 10px; border-radius: 6px; background-color: #2ea043; color: white;"
        )

    def _on_view_friend_requests(self) -> None:
        self._pending_req_btn.setText("📩 Friend Requests")
        self._pending_req_btn.setStyleSheet("margin: 6px 10px; border-radius: 6px;")
        self._network.send_get_pending_requests()

    def _show_friend_requests_dialog(self, requests: list[str]) -> None:
        from client.gui.dialogs import FriendRequestsDialog

        dlg = FriendRequestsDialog(
            requests, self._on_accept_friend, self._on_decline_friend, parent=self
        )
        dlg.exec()

    def _on_accept_friend(self, from_user: str) -> None:
        self._network.send_accept_friend(from_user)

    def _on_decline_friend(self, from_user: str) -> None:
        self._network.send_decline_friend(from_user)

    def _is_joined_room(self, room_name: str, meta: dict | None = None) -> bool:
        meta = meta or self._room_meta.get(room_name, {})
        return bool(meta.get("is_member") or room_name in self._joined_rooms)

    def _attach_list_item_widget(
        self,
        list_widget: QListWidget,
        item: QListWidgetItem,
        text: str,
        on_click,
        on_menu,
        show_menu: bool = True,
    ) -> None:
        item.setData(LIST_DISPLAY_ROLE, text)
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row.setFixedHeight(38)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 0, 4, 0)
        row_layout.setSpacing(6)

        label = QLabel(text)
        label.setObjectName("list_item_label")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setMinimumWidth(0)
        label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        label.setStyleSheet(
            "color: #CBD5E1; background: transparent; "
            "font-size: 14px; font-weight: 500;"
        )
        row_layout.addWidget(label, stretch=1)

        if show_menu:
            more_btn = QPushButton("...")
            more_btn.setFixedSize(26, 26)
            more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            more_btn.setToolTip("More actions")
            more_btn.setStyleSheet(
                """
                QPushButton {
                    background-color: rgba(51, 65, 85, 0.72);
                    color: #CBD5E1;
                    border: none;
                    border-radius: 6px;
                    padding: 0;
                    font-size: 14px;
                    font-weight: 800;
                }
                QPushButton:hover {
                    background-color: #334155;
                    color: #F8FAFC;
                }
                """
            )
            more_btn.clicked.connect(
                lambda checked=False, selected_item=item, button=more_btn: on_menu(
                    selected_item, button
                )
            )
            row_layout.addWidget(more_btn)

        def activate(event, selected_item=item) -> None:
            if event.button() == Qt.MouseButton.LeftButton:
                list_widget.setCurrentItem(selected_item)
                on_click(selected_item)

        row.mousePressEvent = activate
        label.mousePressEvent = activate

        list_widget.setItemWidget(item, row)
        item.setText("")
        item.setSizeHint(QSize(0, 42))

    def _set_list_item_text(
        self, list_widget: QListWidget, item: QListWidgetItem, text: str
    ) -> None:
        item.setData(LIST_DISPLAY_ROLE, text)
        row = list_widget.itemWidget(item)
        if not row:
            item.setText(text)
            return
        item.setText("")
        label = row.findChild(QLabel, "list_item_label")
        if label:
            label.setText(text)

    def _list_item_text(self, item: QListWidgetItem) -> str:
        return item.data(LIST_DISPLAY_ROLE) or item.text()

    def _open_room_item_menu(self, item: QListWidgetItem, button: QPushButton) -> None:
        self._room_list.setCurrentItem(item)
        room = item.data(Qt.ItemDataRole.UserRole)
        meta = self._room_meta.get(room, {})
        menu = QMenu(self)

        if meta.get("invite_code"):
            copy_action = menu.addAction("Copy Invite Code")
            copy_action.triggered.connect(
                lambda: self._copy_invite_code(meta["invite_code"])
            )

        if meta.get("created_by") == self._username:
            del_action = menu.addAction("Delete Room")
            del_action.triggered.connect(lambda: self._delete_room_action(room))
        elif self._is_joined_room(room, meta):
            leave_action = menu.addAction("Leave Room")
            leave_action.triggered.connect(lambda: self._leave_room_action(room))

        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _open_online_item_menu(self, item: QListWidgetItem, button: QPushButton) -> None:
        self._online_list.setCurrentItem(item)
        target = item.data(Qt.ItemDataRole.UserRole)
        if not target or target == self._username:
            return
        menu = QMenu(self)
        pm_action = menu.addAction("Chat privately")
        pm_action.triggered.connect(lambda: self._switch_to_pm(target))
        add_action = menu.addAction("Add friend")
        add_action.triggered.connect(lambda: self._network.send_add_friend(target))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _open_friend_item_menu(self, item: QListWidgetItem, button: QPushButton) -> None:
        self._user_list.setCurrentItem(item)
        target = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        pm_action = menu.addAction("✉️  Send PM")
        pm_action.triggered.connect(lambda: self._switch_to_pm(target))
        remove_action = menu.addAction("🔴  Unfriend")
        remove_action.triggered.connect(lambda: self._on_remove_friend(target))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _populate_room_list(self, rooms: list[dict]) -> None:
        self._room_list.clear()
        for r in rooms:
            name = r.get("room_name", "")
            if name:
                self._room_meta[name] = r

        for r in rooms:
            name = r.get("room_name", "")
            if not name or not self._is_joined_room(name, r):
                continue
            label = f"  💬  {name}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._room_list.addItem(item)
            self._attach_list_item_widget(
                self._room_list,
                item,
                label,
                self._on_room_clicked,
                self._open_room_item_menu,
            )
        self._highlight_current_room()

    def _refresh_room_list_ui(self) -> None:
        self._populate_room_list(list(self._room_meta.values()))

    def _mark_room_unread(self, room: str) -> None:
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == room:
                if "🔵" not in self._list_item_text(item):
                    self._set_list_item_text(
                        self._room_list, item, f"  🔵💬  {room}"
                    )
                return

    def _populate_online_list(self, users: list[str]) -> None:
        self._online_users = sorted(users)
        self._online_list.clear()
        for uname in self._online_users:
            label = f"  🟢  {uname}"
            if uname == self._username:
                label += " (you)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, uname)
            self._online_list.addItem(item)
            self._attach_list_item_widget(
                self._online_list,
                item,
                label,
                self._on_online_user_clicked,
                self._open_online_item_menu,
                show_menu=uname != self._username,
            )

    def _populate_friend_list(self, friends: list[dict]) -> None:
        self._user_list.clear()
        for f in friends:
            uname = f["username"]
            online = f["online"]
            has_unread = (
                uname in self._pm_layouts
                and self._pm_layouts[uname].count() > 1
                and uname != self._current_pm_target
            )
            if has_unread:
                icon = "🔵"
            elif online:
                icon = "🟢"
            else:
                icon = "⚫"
            label = f"  {icon}  {uname}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, uname)
            item.setData(Qt.ItemDataRole.UserRole + 1, online)
            self._user_list.addItem(item)
            self._attach_list_item_widget(
                self._user_list,
                item,
                label,
                self._on_user_clicked,
                self._open_friend_item_menu,
            )
        if self._current_pm_target:
            self._highlight_current_user(self._current_pm_target)

    def _mark_user_unread(self, username: str) -> None:
        for i in range(self._user_list.count()):
            item = self._user_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == username:
                if "🔵" not in self._list_item_text(item):
                    self._set_list_item_text(
                        self._user_list, item, f"  🔵  {username}"
                    )
                return

    def _on_send(self) -> None:
        text = self._msg_input.toPlainText().strip()
        if not text:
            return

        if self._current_pm_target:
            self._msg_input.clear()
            self._network.send_private_message(self._current_pm_target, text)
        elif self._current_room:
            self._msg_input.clear()
            self._network.send_broadcast(self._current_room, text)
        else:
            self._status_bar.showMessage(
                "✗  Select a room or a user to chat with.", 3000
            )

    def _insert_emoji(self, emoji: str) -> None:
        self._msg_input.insertPlainText(emoji)
        self._msg_input.setFocus()

    def _current_user_reaction(self, message_id: str) -> str:
        for reaction in self._message_reactions.get(message_id, []):
            if reaction.get("username") == self._username:
                return reaction.get("emoji", "")
        return ""

    def _active_chat_scope(self) -> tuple[str, str] | None:
        if self._current_pm_target:
            return "private", self._current_pm_target
        if self._current_room:
            return "room", self._current_room
        return None

    def _send_reaction_for_message(
        self, message_id: str, emoji: str, is_pm: bool
    ) -> None:
        self._send_reaction_packet(message_id, emoji, is_pm, action="set")

    def _remove_reaction_for_message(self, message_id: str, is_pm: bool) -> None:
        self._send_reaction_packet(message_id, "", is_pm, action="remove")

    def _send_reaction_packet(
        self, message_id: str, emoji: str, is_pm: bool, action: str
    ) -> None:
        if not message_id:
            return
        if is_pm:
            if not self._current_pm_target:
                self._status_bar.showMessage("Open the private chat first.", 3000)
                return
            self._network.send_reaction(
                scope="private",
                target=self._current_pm_target,
                message_id=message_id,
                emoji=emoji,
                action=action,
            )
        else:
            if not self._current_room:
                self._status_bar.showMessage("Open the room first.", 3000)
                return
            self._network.send_reaction(
                scope="room",
                room=self._current_room,
                message_id=message_id,
                emoji=emoji,
                action=action,
            )

    def _on_send_file(self) -> None:
        self._send_selected_attachment(kind="file")

    def _on_send_voice(self) -> None:
        if self._recording_voice:
            self._stop_voice_recording(send=True)
        else:
            self._start_voice_recording()

    def _start_voice_recording(self) -> None:
        active = self._active_chat_scope()
        if not active:
            self._status_bar.showMessage("Select a room or private chat first.", 3000)
            return

        try:
            import pyaudio
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Microphone Unavailable",
                f"PyAudio is required to record voice messages.\n\n{exc}",
            )
            return

        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=VOICE_CHANNELS,
                rate=VOICE_RATE,
                input=True,
                frames_per_buffer=VOICE_CHUNK,
            )
        except Exception as exc:
            pa.terminate()
            QMessageBox.warning(self, "Recording Failed", str(exc))
            return

        self._record_scope = active
        self._record_frames = []
        self._record_stop_event.clear()
        self._recording_voice = True
        self._record_started_at = time.perf_counter()
        if self._voice_button:
            self._voice_button.setText("Stop")
            self._voice_button.setStyleSheet("background-color:#EF4444; color:white;")
        self._status_bar.showMessage("Recording voice message... click Stop to send.")

        def record_loop() -> None:
            try:
                while not self._record_stop_event.is_set():
                    self._record_frames.append(
                        stream.read(VOICE_CHUNK, exception_on_overflow=False)
                    )
            except Exception:
                pass
            finally:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
                pa.terminate()

        self._record_thread = threading.Thread(
            target=record_loop, name="VoiceRecorder", daemon=True
        )
        self._record_thread.start()
        QTimer.singleShot(
            VOICE_MAX_SECONDS * 1000,
            lambda: self._stop_voice_recording(send=True)
            if self._recording_voice
            else None,
        )

    def _recording_failed(self, message: str) -> None:
        self._recording_voice = False
        self._record_stop_event.set()
        if self._voice_button:
            self._voice_button.setText("Voice")
            self._voice_button.setStyleSheet("")
        QMessageBox.warning(self, "Recording Failed", message)

    def _stop_voice_recording(self, send: bool = True) -> None:
        if not self._recording_voice:
            return
        self._recording_voice = False
        self._record_stop_event.set()
        if self._record_thread and self._record_thread.is_alive():
            self._record_thread.join(timeout=2)
        if self._voice_button:
            self._voice_button.setText("Voice")
            self._voice_button.setStyleSheet("")

        frames = list(self._record_frames)
        self._record_frames = []
        if not send:
            return
        if not frames:
            self._status_bar.showMessage("No audio captured.", 3000)
            return

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav:
            wav.setnchannels(VOICE_CHANNELS)
            wav.setsampwidth(VOICE_SAMPLE_WIDTH)
            wav.setframerate(VOICE_RATE)
            wav.writeframes(b"".join(frames))

        raw = wav_buffer.getvalue()
        if len(raw) > MAX_TRANSFER_BYTES:
            QMessageBox.warning(
                self,
                "Voice Message Too Long",
                "Voice message is larger than 5 MB. Please record a shorter one.",
            )
            return

        scope = self._record_scope
        if not scope:
            self._status_bar.showMessage("No active chat for voice message.", 3000)
            return
        chat_scope, target = scope
        duration = max(1, int(time.perf_counter() - self._record_started_at))
        filename = f"voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{duration}s.wav"
        encoded = base64.b64encode(raw).decode("ascii")
        if chat_scope == "room":
            ok = self._network.send_file_transfer(
                scope="room",
                room=target,
                filename=filename,
                data=encoded,
                kind="voice",
            )
        else:
            ok = self._network.send_file_transfer(
                scope="private",
                target=target,
                filename=filename,
                data=encoded,
                kind="voice",
            )
        self._status_bar.showMessage(
            "Voice message sent." if ok else "Failed to send voice message.", 4000
        )

    def _send_selected_attachment(self, kind: str) -> None:
        active = self._active_chat_scope()
        if not active:
            self._status_bar.showMessage("Select a room or private chat first.", 3000)
            return

        if kind == "voice":
            caption = "Select voice note audio"
            file_filter = "Audio Files (*.wav *.mp3 *.m4a *.ogg *.flac);;All Files (*)"
        else:
            caption = "Select file to send"
            file_filter = "All Files (*)"

        path, _ = QFileDialog.getOpenFileName(self, caption, "", file_filter)
        if not path:
            return

        try:
            size = os.path.getsize(path)
        except OSError as exc:
            QMessageBox.warning(self, "File Error", str(exc))
            return

        if size <= 0:
            QMessageBox.warning(self, "File Error", "The selected file is empty.")
            return
        if size > MAX_TRANSFER_BYTES:
            QMessageBox.warning(
                self,
                "File Too Large",
                "Maximum transfer size is 5 MB for this project demo.",
            )
            return

        try:
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
        except OSError as exc:
            QMessageBox.warning(self, "File Error", str(exc))
            return

        scope, target = active
        filename = os.path.basename(path)
        if scope == "room":
            ok = self._network.send_file_transfer(
                scope="room",
                room=target,
                filename=filename,
                data=encoded,
                kind=kind,
            )
        else:
            ok = self._network.send_file_transfer(
                scope="private",
                target=target,
                filename=filename,
                data=encoded,
                kind=kind,
            )
        if ok:
            label = "Voice note" if kind == "voice" else "File"
            self._status_bar.showMessage(f"{label} sent: {filename}", 4000)
        else:
            self._status_bar.showMessage("Failed to send attachment.", 4000)

    def _on_room_clicked(self, item: QListWidgetItem) -> None:
        room = item.data(Qt.ItemDataRole.UserRole)
        if not room:
            return
        self._current_pm_target = None
        self._user_list.clearSelection()
        self._online_list.clearSelection()

        meta = self._room_meta.get(room, {})
        is_member = meta.get("is_member", False) or room in self._joined_rooms

        if not is_member:
            dlg = JoinPasswordDialog(room_name=room, parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            self._switch_to_room(room, password=dlg.password)
        else:
            self._switch_to_room(room)

    def _switch_to_room(self, room: str, password: str = "") -> None:
        self._current_pm_target = None
        self._current_room = room
        self._room_name_label.setText(f"#  {room}")
        self._leave_btn.setText("Leave Room")

        self._highlight_current_room()
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == room:
                self._set_list_item_text(self._room_list, item, f"  💬  {room}")
                break

        if room not in self._joined_rooms:
            self._network.send_join_room(room, password)
            self._joined_rooms.add(room)
            self._refresh_room_list_ui()

        if room in self._room_scrolls:
            self._chat_stack.setCurrentWidget(self._room_scrolls[room])
        else:
            self._chat_stack.setCurrentIndex(0)

        self._chat_header_bar.show()
        self._input_bar.show()
        self._msg_input.setFocus()

    def _switch_to_pm(self, target: str) -> None:
        self._current_pm_target = target
        self._current_room = None
        self._room_list.clearSelection()
        self._online_list.clearSelection()
        self._room_name_label.setText(f"💬  {target}")

        for i in range(self._user_list.count()):
            item = self._user_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == target:
                online = item.data(Qt.ItemDataRole.UserRole + 1)
                icon = "🟢" if online else "⚫"
                self._set_list_item_text(
                    self._user_list, item, f"  {icon}  {target}"
                )
                break

        self._leave_btn.setText("Close Chat")

        self._network.send_get_pm_history(target)

        if target in self._pm_scrolls:
            self._chat_stack.setCurrentWidget(self._pm_scrolls[target])
        else:
            self._chat_stack.setCurrentIndex(0)

        self._chat_header_bar.show()
        self._input_bar.show()
        self._msg_input.setFocus()

    def _on_create_room(self) -> None:
        dlg = CreateRoomDialog(parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._network.send_create_room(dlg.room_name)

    def _on_join_by_code(self) -> None:
        dlg = JoinPasswordDialog(room_name="", parent=self)
        dlg.setWindowTitle("Join a Room")
        if dlg.exec() == dlg.DialogCode.Accepted:
            code = dlg.password.strip().upper()
            if code:
                self._network.send_join_by_code(code)

    def _on_leave_room(self) -> None:
        if self._current_room:
            room = self._current_room
            ans = QMessageBox.question(
                self,
                "Leave Room",
                f"Leave room '{room}'? You will need the invite code to join again.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self._leave_room_action(room)
            return

        self._current_pm_target = None
        self._current_room = None
        self._room_name_label.setText("Select a room →")
        self._leave_btn.setText("Close Chat")
        self._chat_stack.setCurrentIndex(0)
        self._user_list.clearSelection()
        self._online_list.clearSelection()
        self._room_list.clearSelection()
        self._chat_header_bar.hide()
        self._input_bar.hide()

    def _on_room_context_menu(self, pos) -> None:
        item = self._room_list.itemAt(pos)
        if not item:
            return
        room = item.data(Qt.ItemDataRole.UserRole)
        meta = self._room_meta.get(room, {})
        menu = QMenu(self)

        if meta.get("invite_code"):
            copy_action = menu.addAction("Copy Invite Code")
            copy_action.triggered.connect(
                lambda: self._copy_invite_code(meta["invite_code"])
            )

        if meta.get("created_by") == self._username:
            del_action = menu.addAction("Delete Room")
            del_action.triggered.connect(lambda: self._delete_room_action(room))
        elif meta.get("is_member") or room in self._joined_rooms:
            leave_action = menu.addAction("Leave Room")
            leave_action.triggered.connect(lambda: self._leave_room_action(room))
        else:
            join_action = menu.addAction("Join Room")
            join_action.triggered.connect(lambda: self._switch_to_room_from_menu(room))

        menu.exec(self._room_list.mapToGlobal(pos))

    def _switch_to_room_from_menu(self, room: str) -> None:
        self._current_pm_target = None
        dlg = JoinPasswordDialog(room_name=room, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._switch_to_room(room, password=dlg.password)

    def _copy_invite_code(self, code: str) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(code)
        self._status_bar.showMessage(f"✓  Copied invite code: {code}", 3000)

    def _delete_room_action(self, room: str) -> None:
        from PyQt6.QtWidgets import QMessageBox

        ans = QMessageBox.question(
            self,
            "Delete Room",
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
            self._chat_stack.setCurrentIndex(0)
            self._chat_header_bar.hide()
            self._input_bar.hide()
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
        self._switch_to_pm(target)

    def _on_online_user_clicked(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if not target or target == self._username:
            return
        self._switch_to_pm(target)

    def _on_online_context_menu(self, pos) -> None:
        item = self._online_list.itemAt(pos)
        if not item:
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        if not target or target == self._username:
            return
        menu = QMenu(self)
        pm_action = menu.addAction("Chat privately")
        pm_action.triggered.connect(lambda: self._switch_to_pm(target))
        add_action = menu.addAction("Add friend")
        add_action.triggered.connect(lambda: self._network.send_add_friend(target))
        menu.exec(self._online_list.mapToGlobal(pos))

    def _on_friend_context_menu(self, pos) -> None:
        item = self._user_list.itemAt(pos)
        if not item:
            return
        target = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        pm_action = menu.addAction("✉️  Send PM")
        pm_action.triggered.connect(lambda: self._switch_to_pm(target))
        remove_action = menu.addAction("🔴  Unfriend")
        remove_action.triggered.connect(lambda: self._on_remove_friend(target))
        menu.exec(self._user_list.mapToGlobal(pos))

    def _on_add_friend(self) -> None:
        dlg = AddFriendDialog(parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._network.send_add_friend(dlg.username)

    def _on_remove_friend(self, target: str) -> None:
        from PyQt6.QtWidgets import QMessageBox

        ans = QMessageBox.question(
            self,
            "Remove Friend",
            f"Remove '{target}' from your friends list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._network.send_remove_friend(target)
            if self._current_pm_target == target:
                self._current_pm_target = None
                self._room_name_label.setText("Select a room →")
                self._leave_btn.setText("Close Chat")
                self._chat_stack.setCurrentIndex(0)
                self._chat_header_bar.hide()
                self._input_bar.hide()

    def _on_refresh(self) -> None:
        if not self._network.is_connected:
            self._status_bar.showMessage("Reconnecting...", 2000)
            ok, err = self._network.connect_to_server()
            if not ok:
                self._status_bar.showMessage(f"Reconnection failed: {err}", 5000)
                return
            
            self._network.send_login(self._username, self._password)
            
            for room in list(self._joined_rooms):
                self._network.send_join_room(room)
                
            if self._current_pm_target:
                self._network.send_get_pm_history(self._current_pm_target)

        self._network.send_get_rooms()
        self._network.send_get_users()
        self._network.send_get_friends()
        self._status_bar.showMessage("Refreshed.", 2000)

    def _on_logout(self) -> None:
        self._logged_out = True
        self._network.send_logout()
        self._network.disconnect()
        self.close()

    def _on_disconnected(self) -> None:
        if self._current_room:
            self._add_chat_bubble(
                self._current_room,
                False,
                {
                    "type": "system",
                    "message": "⚠  Disconnected from server.",
                    "color": RED,
                },
            )
        self._status_bar.showMessage("Disconnected from server.")

    def closeEvent(self, event) -> None:
        if hasattr(self, "_presence_timer"):
            self._presence_timer.stop()
        if self._recording_voice:
            self._stop_voice_recording(send=False)
        self._audio_player.stop()
        for path in self._voice_temp_files:
            try:
                os.remove(path)
            except OSError:
                pass
        if self._network.is_connected and not self._logged_out:
            self._network.send_logout()
            self._network.disconnect()
        event.accept()
