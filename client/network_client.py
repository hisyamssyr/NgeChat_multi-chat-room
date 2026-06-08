# Qt-aware networking bridge for the PyQt6 GUI client.

import socket
import threading
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QObject, pyqtSignal

from client.protocol import (
    send_packet,
    recv_packet,
    build_register,
    build_login,
    build_logout,
    build_create_room,
    build_join_room,
    build_join_by_code,
    build_leave_room,
    build_broadcast,
    build_private_message,
    build_get_rooms,
    build_get_users,
)

logger = logging.getLogger(__name__)

class NetworkClient(QObject):
    # Thread-safe Qt bridge for the TCP chat protocol.

    packet_received     = pyqtSignal(dict)
    connected_signal    = pyqtSignal()
    disconnected_signal = pyqtSignal()
    error_signal        = pyqtSignal(str)

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host       = host
        self._port       = port
        self._sock: socket.socket | None = None
        self._connected  = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect_to_server(self) -> tuple[bool, str]:
        # Establish a TCP connection and start the receiver daemon thread.
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(5.0)
            self._sock.connect((self._host, self._port))
            self._sock.settimeout(None)   # switch to blocking after connect
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
            msg = (
                f"Connection refused — is the server running "
                f"on {self._host}:{self._port}?"
            )
            return False, msg
        except TimeoutError:
            return False, f"Connection timed out to {self._host}:{self._port}."
        except OSError as exc:
            return False, str(exc)

    def disconnect(self) -> None:
        # Cleanly shut down the connection.
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
    # Sending — convenience wrappers around protocol builders
    # ------------------------------------------------------------------

    def send(self, packet: dict) -> bool:
        # Send a pre-built packet dict.
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

    def send_broadcast(self, room: str, message: str) -> bool:
        return self.send(build_broadcast(room, message))

    def send_private_message(self, target: str, message: str) -> bool:
        return self.send(build_private_message(target, message))

    def send_get_rooms(self) -> bool:
        return self.send(build_get_rooms())

    def send_get_users(self) -> bool:
        return self.send(build_get_users())

    # ------------------------------------------------------------------
    # Receiver thread
    # ------------------------------------------------------------------

    def _receiver_loop(self) -> None:
        # Background daemon thread.
        while not self._stop_event.is_set():
            packet = recv_packet(self._sock)

            if packet is None:
                # Server closed the connection.
                if not self._stop_event.is_set():
                    self._connected = False
                    self.disconnected_signal.emit()
                break

            if packet:   # skip empty / malformed
                self.packet_received.emit(packet)

        logger.debug("GUI-ReceiverThread exited.")
