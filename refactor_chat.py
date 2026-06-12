import os
import re

file_path = r"client\gui\main_window.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Remove old HTML formatters
html_funcs_regex = re.compile(r"def _fmt_ts.*?def _html_pm_out.*?return\s+\(\s+.*?</table>'\s+\)\s+", re.DOTALL)
content = html_funcs_regex.sub("def _fmt_ts(timestamp: str) -> str:\n    try:\n        return timestamp.split(\" \")[1][:5]\n    except Exception:\n        return \"\"\n\n", content)

# 2. Add imports for QStackedWidget and QScrollArea
content = content.replace("from PyQt6.QtWidgets import (", "from PyQt6.QtWidgets import (\n    QStackedWidget, QScrollArea,")
content = content.replace("QTextBrowser,", "QTextBrowser, QSizePolicy,")

# 3. Update __init__
init_replacement = """        self._current_room: str | None       = None
        self._current_pm_target: str | None  = None
        self._joined_rooms: set[str]         = set()
        
        # New QScrollArea-based storage
        self._room_scrolls: dict[str, QScrollArea] = {}
        self._room_layouts: dict[str, QVBoxLayout] = {}
        self._pm_scrolls: dict[str, QScrollArea]   = {}
        self._pm_layouts: dict[str, QVBoxLayout]   = {}
        
        self._room_meta: dict[str, dict]      = {}"""

content = re.sub(r"self\._current_room: str \| None.*?self\._room_meta: dict\[str, dict\]\s+=\s+\{\}", init_replacement, content, flags=re.DOTALL)

# 4. Update _setup_ui for chat_frame min width
content = content.replace(
    'chat_frame.setObjectName("chat_frame")',
    'chat_frame.setObjectName("chat_frame")\n        chat_frame.setMinimumWidth(350)'
)

# 5. Update _setup_ui for _chat_area -> _chat_stack
chat_area_code = """        self._chat_area = QTextBrowser()
        self._chat_area.setObjectName("chat_area")
        self._chat_area.setOpenLinks(False)
        self._chat_area.setReadOnly(True)
        cv.addWidget(self._chat_area, stretch=1)"""
chat_stack_code = """        self._chat_stack = QStackedWidget()
        cv.addWidget(self._chat_stack, stretch=1)
        
        # Default empty page
        empty_page = QWidget()
        empty_page.setStyleSheet("background-color: transparent;")
        self._chat_stack.addWidget(empty_page)
        self._chat_stack.setCurrentWidget(empty_page)"""
content = content.replace(chat_area_code, chat_stack_code)

# 6. Delete _append_to_chat, _store_and_show, _reload_chat, _scroll_to_bottom
chat_rendering_regex = re.compile(r"    # ------------------------------------------------------------------\n    # Chat rendering\n    # ------------------------------------------------------------------\n\n.*?    # ------------------------------------------------------------------\n    # Room list helpers", re.DOTALL)

new_chat_rendering = """    # ------------------------------------------------------------------
    # Chat rendering (QScrollArea + QWidget)
    # ------------------------------------------------------------------

    def _get_or_create_chat(self, target: str, is_pm: bool):
        scrolls = self._pm_scrolls if is_pm else self._room_scrolls
        layouts = self._pm_layouts if is_pm else self._room_layouts
        
        if target in scrolls:
            return scrolls[target], layouts[target]
            
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch() # Push everything to bottom
        
        scroll.setWidget(container)
        scrolls[target] = scroll
        layouts[target] = layout
        
        self._chat_stack.addWidget(scroll)
        return scroll, layout

    def _add_chat_bubble(self, target: str, is_pm: bool, data: dict) -> None:
        scroll, layout = self._get_or_create_chat(target, is_pm)
        widget = self._create_bubble_widget(data)
        layout.insertWidget(layout.count() - 1, widget)
        
        # Auto-scroll
        if (is_pm and target == self._current_pm_target) or (not is_pm and target == self._current_room):
            self._chat_stack.setCurrentWidget(scroll)
            QTimer.singleShot(30, lambda: scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()))
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
            lbl.setStyleSheet(f"color: {p.get('color', '#94A3B8')}; font-size: 13px; font-weight: 500;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(lbl)
            return container
            
        if ptype == "date_separator":
            lbl = QLabel(f"●  {p.get('date')}  ●")
            lbl.setStyleSheet("color: #64748B; font-size: 12px; font-weight: bold; background-color: #1E293B; border-radius: 12px; padding: 4px 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(lbl)
            return container
            
        if ptype == "notification":
            lbl = QLabel(msg)
            lbl.setStyleSheet("color: #94A3B8; font-size: 12px; font-style: italic; background-color: #1E293B; border-radius: 12px; padding: 4px 12px;")
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
            
        msg_lbl = QLabel(msg.replace('&', '&&'))  # QLabel uses & for shortcuts, escape it
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet("color: #F8FAFC; font-size: 14px; background-color: transparent;")
        msg_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        blayout.addWidget(msg_lbl)
        
        ts_lbl = QLabel(ts)
        color = "#C4B5FD" if is_pm else ("#A5B4FC" if is_own else "#94A3B8")
        ts_lbl.setStyleSheet(f"color: {color}; font-size: 10px; background-color: transparent;")
        ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        blayout.addWidget(ts_lbl)
        
        if is_own:
            bg = "#5B21B6" if is_pm else "#4F46E5"
            bubble.setStyleSheet(f"background-color: {bg}; border-radius: 16px; border-top-right-radius: 4px;")
            row.addStretch()
            row.addWidget(bubble, stretch=1)
            row.addSpacing(20)
        else:
            bg = "#4C1D95" if is_pm else "#1E293B"
            b_style = f"background-color: {bg}; border-radius: 16px; border-top-left-radius: 4px;"
            if is_pm:
                b_style += " border-left: 4px solid #8B5CF6;"
            bubble.setStyleSheet(b_style)
            row.addSpacing(20)
            row.addWidget(bubble, stretch=1)
            row.addStretch()
            
        return container

    # ------------------------------------------------------------------
    # Room list helpers"""

content = chat_rendering_regex.sub(new_chat_rendering, content)

# 7. Update on_packet uses
# Change _append_to_chat(_html_notification(...)) -> _add_chat_bubble(self._current_room, False, {"type":"notification", "message":...})
# Change _append_to_chat(_html_system(...)) -> _add_chat_bubble(self._current_room, False, {"type":"system", "message":..., "color":...})

# System messages in on_disconnected
content = content.replace(
    'self._append_to_chat(_html_system("⚠  Disconnected from server.", RED))',
    'if self._current_room:\n            self._add_chat_bubble(self._current_room, False, {"type": "system", "message": "⚠  Disconnected from server.", "color": RED})'
)

# Room packet handling (broadcast)
broadcast_handling = """        if ptype == "broadcast":
            room = packet.get("room_name")
            if not room: return
            
            data = {
                "type": "broadcast",
                "sender": packet.get("sender", "?"),
                "message": packet.get("message", ""),
                "timestamp": packet.get("timestamp", ""),
                "is_own": packet.get("sender", "") == self._username
            }
            self._add_chat_bubble(room, False, data)
            return"""
content = re.sub(r"        if ptype == \"broadcast\":.*?return", broadcast_handling, content, flags=re.DOTALL)

# Room history
history_handling = """        if ptype == "room_history":
            room = packet.get("room_name")
            messages = packet.get("messages", [])
            if not room: return
            
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
                    layout.insertWidget(layout.count() - 1, self._create_bubble_widget({"type": "date_separator", "date": date_str}))
                    last_date = date_str
                    
                data = {
                    "type": "broadcast",
                    "sender": m.get("sender", "?"),
                    "message": m.get("message", ""),
                    "timestamp": ts,
                    "is_own": m.get("sender", "") == self._username
                }
                layout.insertWidget(layout.count() - 1, self._create_bubble_widget(data))
                
            if room == self._current_room:
                self._chat_stack.setCurrentWidget(scroll)
                QTimer.singleShot(30, lambda: scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()))
            return"""
content = re.sub(r"        if ptype == \"room_history\":.*?return", history_handling, content, flags=re.DOTALL)

# System and Notifications handling in room_list, etc. (Actually those didn't use _append_to_chat except join)
join_sys = """        if ptype == "room_join_success":
            room = packet.get("room_name")
            if room:
                self._joined_rooms.add(room)
                self._refresh_room_list_ui()
            return"""
content = re.sub(r"        if ptype == \"room_join_success\":.*?return", join_sys, content, flags=re.DOTALL)

member_join = """        if ptype == "member_joined":
            room = packet.get("room_name")
            who  = packet.get("username")
            if room and who:
                self._add_chat_bubble(room, False, {"type": "notification", "message": f"{who} joined the room."})
            return"""
content = re.sub(r"        if ptype == \"member_joined\":.*?return", member_join, content, flags=re.DOTALL)

member_left = """        if ptype == "member_left":
            room = packet.get("room_name")
            who  = packet.get("username")
            if room and who:
                self._add_chat_bubble(room, False, {"type": "notification", "message": f"{who} left the room."})
            return"""
content = re.sub(r"        if ptype == \"member_left\":.*?return", member_left, content, flags=re.DOTALL)

# Private message packet
pm_recv = """        if ptype == "private_message":
            sender = packet.get("sender")
            msg    = packet.get("message", "")
            ts     = packet.get("timestamp", "")
            if not sender: return
            
            data = {
                "type": "pm",
                "sender": sender,
                "message": msg,
                "timestamp": ts,
                "is_own": False,
                "is_pm": True
            }
            self._add_chat_bubble(sender, True, data)
            return"""
content = re.sub(r"        if ptype == \"private_message\":.*?return", pm_recv, content, flags=re.DOTALL)

# In _on_send:
send_pm = """        if self._current_pm_target:
            self._msg_input.clear()
            self._network.send_private_message(self._current_pm_target, text)
            
            # Local echo
            data = {
                "type": "pm",
                "sender": self._username,
                "message": text,
                "timestamp": "now",  # server assigns actual, but local echo needs fake
                "is_own": True,
                "is_pm": True
            }
            self._add_chat_bubble(self._current_pm_target, True, data)
            return"""
content = re.sub(r"        if self\._current_pm_target:.*?return", send_pm, content, flags=re.DOTALL)

# Remove `_reload_chat` calls in `_switch_to_room` and `_switch_to_pm`
# Replace with setting the current widget
content = content.replace("self._reload_chat()", "")

# In _switch_to_room:
switch_room_add = """        if room in self._room_scrolls:
            self._chat_stack.setCurrentWidget(self._room_scrolls[room])
        else:
            self._chat_stack.setCurrentIndex(0) # empty page"""
content = content.replace("self._chat_header_bar.show()", switch_room_add + "\n\n        self._chat_header_bar.show()")

# In _switch_to_pm:
switch_pm_add = """        if target in self._pm_scrolls:
            self._chat_stack.setCurrentWidget(self._pm_scrolls[target])
        else:
            self._chat_stack.setCurrentIndex(0)"""
# It has two self._chat_header_bar.show() now? Wait, replace works globally.
content = re.sub(r"        self\._leave_btn\.setText\(\"Close Chat\"\)\n\s+self\._chat_header_bar\.show\(\)", "        self._leave_btn.setText(\"Close Chat\")\n" + switch_pm_add + "\n        self._chat_header_bar.show()", content, count=1)


# Clear chat areas
content = content.replace("self._chat_area.clear()", "self._chat_stack.setCurrentIndex(0)")

# Remove unused _pm_logs reference in _populate_friend_list
content = content.replace("uname in self._pm_logs", "uname in self._pm_layouts and self._pm_layouts[uname].count() > 1")

# Delete `_store_pm`
content = re.sub(r"    def _store_pm\(self, contact: str, html: str\) -> None:.*?(?=    # ------------------------------------------------------------------)", "", content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
