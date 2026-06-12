# In-memory state manager for the Multi-Chat Room Server.

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class RoomManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._online_users: dict[str, Any] = {}  # username → socket
        self._room_members: dict[str, set[str]] = {}  # room → {usernames}

    # Online-user management

    def add_user(self, username: str, sock) -> None:
        with self._lock:
            self._online_users[username] = sock
            logger.info("User came online: %s", username)

    def remove_user(self, username: str) -> None:
        with self._lock:
            if username not in self._online_users:
                return

            del self._online_users[username]

            departed_rooms = [
                room
                for room, members in self._room_members.items()
                if username in members
            ]
            for room in departed_rooms:
                self._room_members[room].discard(username)
                if not self._room_members[room]:
                    del self._room_members[room]

            logger.info(
                "User went offline: %s (was in rooms: %s)",
                username,
                departed_rooms,
            )

    def is_online(self, username: str) -> bool:
        with self._lock:
            return username in self._online_users

    def get_socket(self, username: str):
        with self._lock:
            return self._online_users.get(username)

    def get_online_users(self) -> list[str]:
        with self._lock:
            return sorted(self._online_users.keys())

    def online_user_count(self) -> int:
        with self._lock:
            return len(self._online_users)

    # Room-membership management

    def join_room(self, username: str, room_name: str) -> bool:
        with self._lock:
            members = self._room_members.setdefault(room_name, set())
            if username in members:
                return False
            members.add(username)
            logger.info("'%s' joined room '%s'", username, room_name)
            return True

    def leave_room(self, username: str, room_name: str) -> bool:
        with self._lock:
            members = self._room_members.get(room_name)
            if not members or username not in members:
                return False

            members.discard(username)
            if not members:
                del self._room_members[room_name]

            logger.info("'%s' left room '%s'", username, room_name)
            return True

    def delete_room(self, room_name: str) -> list[str]:
        with self._lock:
            if room_name in self._room_members:
                members = list(self._room_members[room_name])
                del self._room_members[room_name]
                logger.info(
                    "Room '%s' was deleted and removed from active tracking.", room_name
                )
                return members
            return []

    def is_in_room(self, username: str, room_name: str) -> bool:
        with self._lock:
            return username in self._room_members.get(room_name, set())

    def get_room_members(self, room_name: str) -> list[str]:
        with self._lock:
            return sorted(self._room_members.get(room_name, set()))

    def get_user_rooms(self, username: str) -> list[str]:
        with self._lock:
            return sorted(
                room
                for room, members in self._room_members.items()
                if username in members
            )

    def active_room_count(self) -> int:
        with self._lock:
            return len(self._room_members)

    # Push-message delivery

    def broadcast_to_room(
        self,
        room_name: str,
        packet: dict,
        exclude: str | None = None,
    ) -> int:
        from server.protocol import send_packet  # local import — avoids circular dep

        with self._lock:
            members = list(self._room_members.get(room_name, set()))

        sent = 0
        for username in members:
            if username == exclude:
                continue
            sock = self.get_socket(username)
            if sock and send_packet(sock, packet):
                sent += 1

        return sent

    def send_to_user(self, username: str, packet: dict) -> bool:
        from server.protocol import send_packet  # local import — avoids circular dep

        sock = self.get_socket(username)
        if sock is None:
            return False
        return send_packet(sock, packet)

    # Diagnostics

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "online_users": list(self._online_users.keys()),
                "room_members": {
                    room: list(members) for room, members in self._room_members.items()
                },
            }
