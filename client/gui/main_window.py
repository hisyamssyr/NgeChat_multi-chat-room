import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
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
        self.setPlaceholderText(
            "Type a message…  (Enter to send, Shift+Enter for newline)"
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._on_send()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):

    def __init__(self, network: NetworkClient, username: str) -> None:
        super().__init__()
        self._network = network
        self._username = username
        self._current_room: str | None = None
        self._current_pm_target: str | None = None
        self._joined_rooms: set[str] = set()

        self._room_scrolls: dict[str, QScrollArea] = {}
        self._room_layouts: dict[str, QVBoxLayout] = {}
        self._pm_scrolls: dict[str, QScrollArea] = {}
        self._pm_layouts: dict[str, QVBoxLayout] = {}

        self._room_meta: dict[str, dict] = {}
        self._friend_data: list[dict] = []
        self._logged_out = False

        self.setWindowTitle(f"Multi-Chat Room  —  {username}")
        self.setMinimumSize(900, 620)
        self.resize(1100, 700)

        self._setup_ui()
        self._connect_signals()

        QTimer.singleShot(300, self._initial_fetch)

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
        self._chat_header_bar.setStyleSheet(
            "background-color: #1E293B; border-bottom: 1px solid #475569;"
        )
        chh = QHBoxLayout(self._chat_header_bar)
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
        bar.setFixedHeight(80)
        bar.setStyleSheet("background-color: #1E293B; border-top: 1px solid #475569;")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(12)

        self._msg_input = _MsgInput(on_send_callback=self._on_send)
        h.addWidget(self._msg_input, stretch=1)

        send_btn = QPushButton("Send  ▶")
        send_btn.setObjectName("send_btn")
        send_btn.setFixedWidth(100)
        send_btn.clicked.connect(self._on_send)
        h.addWidget(send_btn)

        return bar

    def _connect_signals(self) -> None:
        self._network.packet_received.connect(self.on_packet)
        self._network.disconnected_signal.connect(self._on_disconnected)

    def _initial_fetch(self) -> None:
        self._network.send_get_rooms()
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
                "sender": packet.get("sender", "?"),
                "message": packet.get("message", ""),
                "timestamp": packet.get("timestamp", ""),
                "is_own": packet.get("sender", "") == self._username,
            }
            self._add_chat_bubble(room, False, data)
            return

        if ptype == "private_message":
            sender = packet.get("sender")
            msg = packet.get("message", "")
            ts = packet.get("timestamp", "")
            if not sender:
                return

            data = {
                "type": "pm",
                "sender": sender,
                "message": msg,
                "timestamp": ts,
                "is_own": False,
                "is_pm": True,
            }
            self._add_chat_bubble(sender, True, data)
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

                data = {
                    "type": "broadcast",
                    "sender": m.get("sender", "?"),
                    "message": m.get("message", ""),
                    "timestamp": ts,
                    "is_own": m.get("sender", "") == self._username,
                }
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

                data = {
                    "type": "pm",
                    "sender": m.get("sender", "?"),
                    "message": m.get("message", ""),
                    "timestamp": ts,
                    "is_own": m.get("sender", "") == self._username,
                    "is_pm": True,
                }
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

        is_own = p.get("is_own", False)
        sender = p.get("sender", "")
        is_pm = p.get("is_pm", False)

        bubble = QFrame()
        blayout = QVBoxLayout(bubble)
        blayout.setContentsMargins(14, 10, 14, 8)
        blayout.setSpacing(4)

        if not is_own and sender:
            s_lbl = QLabel(sender + (" (private)" if is_pm else ""))
            color = "#C4B5FD" if is_pm else "#6366F1"
            s_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            blayout.addWidget(s_lbl)

        msg_lbl = QLabel(msg.replace("&", "&&"))
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            "color: #F8FAFC; font-size: 14px; background-color: transparent;"
        )
        msg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        blayout.addWidget(msg_lbl)

        ts_lbl = QLabel(ts)
        color = "#C4B5FD" if is_pm else ("#A5B4FC" if is_own else "#94A3B8")
        ts_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background-color: transparent;"
        )
        ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        blayout.addWidget(ts_lbl)

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

    def _on_send(self) -> None:
        text = self._msg_input.toPlainText().strip()
        if not text:
            return

        if self._current_pm_target:
            self._msg_input.clear()
            self._network.send_private_message(self._current_pm_target, text)

            data = {
                "type": "pm",
                "sender": self._username,
                "message": text,
                "timestamp": "now",
                "is_own": True,
                "is_pm": True,
            }
            self._add_chat_bubble(self._current_pm_target, True, data)
        elif self._current_room:
            self._msg_input.clear()
            self._network.send_broadcast(self._current_room, text)
        else:
            self._status_bar.showMessage(
                "✗  Select a room or a user to chat with.", 3000
            )

    def _on_room_clicked(self, item: QListWidgetItem) -> None:
        room = item.data(Qt.ItemDataRole.UserRole)
        if not room:
            return
        self._current_pm_target = None
        self._user_list.clearSelection()

        meta = self._room_meta.get(room, {})
        is_member = meta.get("is_member", False) or room in self._joined_rooms

        if not is_member:
            dlg = JoinPasswordDialog(room_name=room, parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            self._room_meta.setdefault(room, {})["is_member"] = True
            self._switch_to_room(room, password=dlg.password)
        else:
            self._switch_to_room(room)

    def _switch_to_room(self, room: str, password: str = "") -> None:
        self._current_pm_target = None
        self._current_room = room
        self._room_name_label.setText(f"#  {room}")
        self._leave_btn.setText("Close Chat")

        self._highlight_current_room()
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == room:
                item.setText(f"  💬  {room}")
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
        self._room_name_label.setText(f"💬  {target}")

        for i in range(self._user_list.count()):
            item = self._user_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == target:
                online = item.data(Qt.ItemDataRole.UserRole + 1)
                icon = "🟢" if online else "⚫"
                item.setText(f"  {icon}  {target}")
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
        self._current_pm_target = None
        self._current_room = None
        self._room_name_label.setText("Select a room →")
        self._leave_btn.setText("Close Chat")
        self._chat_stack.setCurrentIndex(0)
        self._user_list.clearSelection()
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
        self._network.send_get_rooms()
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
        if self._network.is_connected and not self._logged_out:
            self._network.send_logout()
            self._network.disconnect()
        event.accept()
