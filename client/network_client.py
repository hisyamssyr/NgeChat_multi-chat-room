"""Qt-aware networking bridge: runs a background thread that reads packets
and emits them as Qt signals so the GUI thread can process them safely."""

import logging
import os
import socket
import ssl
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QObject, pyqtSignal

from client.protocol import (
    build_accept_friend,
    build_add_friend,
    build_broadcast,
    build_create_room,
    build_decline_friend,
    build_delete_room,
    build_file_transfer,
    build_get_friends,
    build_get_rooms,
    build_get_users,
    build_join_by_code,
    build_join_room,
    build_leave_room,
    build_login,
    build_logout,
    build_private_message,
    build_reaction,
    build_register,
    build_remove_friend,
    recv_packet,
    send_packet,
)

logger = logging.getLogger(__name__)


class NetworkClient(QObject):
    packet_received = pyqtSignal(dict)
    connected_signal = pyqtSignal()
    disconnected_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._connected = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect_to_server(self) -> tuple[bool, str]:
        try:
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_sock.settimeout(5.0)

            # Setup TLS context (accepting self-signed certs)
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            self._sock = context.wrap_socket(raw_sock, server_hostname=self._host)
            self._sock.connect((self._host, self._port))

            self._sock.settimeout(None)  # switch to blocking after connect
            self._connected = True
            self._stop_event.clear()

            self._thread = threading.Thread(
                target=self._receiver_loop,
                name="GUI-ReceiverThread",
                daemon=True,
            )
            self._thread.start()

            self.connected_signal.emit()
            logger.info("Connected to %s:%d", self._host, self._port)
            return True, ""

        except ConnectionRefusedError:
            return (
                False,
                f"Connection refused — is the server running on {self._host}:{self._port}?",
            )
        except TimeoutError:
            return False, f"Connection timed out to {self._host}:{self._port}."
        except OSError as exc:
            return False, str(exc)

    def disconnect(self) -> None:
        self._connected = False
        self._stop_event.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        logger.info("Disconnected from server.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    def send(self, packet: dict) -> bool:
        if not self._connected or not self._sock:
            return False
        return send_packet(self._sock, packet)

    def send_register(self, username: str, password: str) -> bool:
        return self.send(build_register(username, password))

    def send_login(self, username: str, password: str) -> bool:
        return self.send(build_login(username, password))

    def send_logout(self) -> bool:
        return self.send(build_logout())

    def send_create_room(self, room: str) -> bool:
        return self.send(build_create_room(room))

    def send_join_room(self, room: str, code: str = "") -> bool:
        return self.send(build_join_room(room, code))

    def send_join_by_code(self, code: str) -> bool:
        return self.send(build_join_by_code(code))

    def send_leave_room(self, room: str) -> bool:
        return self.send(build_leave_room(room))

    def send_delete_room(self, room: str) -> bool:
        return self.send(build_delete_room(room))

    def send_broadcast(self, room: str, message: str) -> bool:
        return self.send(build_broadcast(room, message))

    def send_private_message(self, target: str, message: str) -> bool:
        return self.send(build_private_message(target, message))

    def send_file_transfer(
        self,
        *,
        scope: str,
        filename: str,
        data: str,
        room: str = "",
        target: str = "",
        kind: str = "file",
    ) -> bool:
        return self.send(
            build_file_transfer(
                scope=scope,
                filename=filename,
                data=data,
                room=room,
                target=target,
                kind=kind,
            )
        )

    def send_reaction(
        self,
        *,
        scope: str,
        message_id: str,
        emoji: str,
        action: str = "set",
        room: str = "",
        target: str = "",
    ) -> bool:
        return self.send(
            build_reaction(
                scope=scope,
                message_id=message_id,
                emoji=emoji,
                action=action,
                room=room,
                target=target,
            )
        )

    def send_get_rooms(self) -> bool:
        return self.send(build_get_rooms())

    def send_get_users(self) -> bool:
        return self.send(build_get_users())

    def send_get_pm_history(self, target: str) -> bool:
        from client.protocol import build_get_pm_history

        return self.send(build_get_pm_history(target))

    def send_get_friends(self) -> bool:
        return self.send(build_get_friends())

    def send_add_friend(self, target: str) -> bool:
        return self.send(build_add_friend(target))

    def send_remove_friend(self, target: str) -> bool:
        return self.send(build_remove_friend(target))

    def send_accept_friend(self, target: str) -> bool:
        return self.send(build_accept_friend(target))

    def send_decline_friend(self, target: str) -> bool:
        return self.send(build_decline_friend(target))

    def send_get_pending_requests(self) -> bool:
        from client.protocol import build_get_pending_requests

        return self.send(build_get_pending_requests())

    # ------------------------------------------------------------------
    # Receiver thread
    # ------------------------------------------------------------------

    def _receiver_loop(self) -> None:
        while not self._stop_event.is_set():
            packet = recv_packet(self._sock)

            if packet is None:
                # Server closed the connection (not a client-side stop).
                if not self._stop_event.is_set():
                    self._connected = False
                    self.disconnected_signal.emit()
                break

            if packet:  # skip empty / malformed
                self.packet_received.emit(packet)

        logger.debug("GUI-ReceiverThread exited.")
