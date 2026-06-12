"""Client-side wire-protocol: framing, parsing, and packet builders."""

import json
import struct
import logging

logger = logging.getLogger(__name__)

_LENGTH_FORMAT  = "!I"
_LENGTH_SIZE    = struct.calcsize(_LENGTH_FORMAT)
MAX_PACKET_SIZE = 16 * 1024 * 1024  # 16 MB guard


def send_packet(sock, data: dict) -> bool:
    try:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        sock.sendall(struct.pack(_LENGTH_FORMAT, len(payload)) + payload)
        return True
    except (OSError, BrokenPipeError) as exc:
        logger.debug("send_packet failed: %s", exc)
        return False


def recv_packet(sock) -> dict | None:
    header = _recv_exactly(sock, _LENGTH_SIZE)
    if header is None:
        return None

    (length,) = struct.unpack(_LENGTH_FORMAT, header)

    if length == 0:
        return {}
    if length > MAX_PACKET_SIZE:
        logger.error("recv_packet: oversized payload (%d bytes). Disconnecting.", length)
        return None

    raw = _recv_exactly(sock, length)
    if raw is None:
        return None

    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("recv_packet: JSON decode error — %s", exc)
        return {}


def _recv_exactly(sock, num_bytes: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < num_bytes:
        try:
            chunk = sock.recv(num_bytes - len(buf))
        except OSError as exc:
            logger.debug("_recv_exactly OSError: %s", exc)
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# -- Packet builders -------------------------------------------------------

def build_register(username: str, password: str) -> dict:
    return {"type": "register", "username": username, "password": password}

def build_login(username: str, password: str) -> dict:
    return {"type": "login", "username": username, "password": password}

def build_logout() -> dict:
    return {"type": "logout"}

def build_create_room(room: str) -> dict:
    return {"type": "create_room", "room": room}

def build_join_room(room: str, code: str = "") -> dict:
    # code is only included when re-joining with an invite (not a plain session re-join)
    packet: dict = {"type": "join_room", "room": room}
    if code:
        packet["code"] = code
    return packet

def build_join_by_code(code: str) -> dict:
    return {"type": "join_by_code", "code": code.strip().upper()}

def build_leave_room(room: str) -> dict:
    return {"type": "leave_room", "room": room}

def build_delete_room(room: str) -> dict:
    return {"type": "delete_room", "room": room}

def build_broadcast(room: str, message: str) -> dict:
    return {"type": "broadcast", "room": room, "message": message}

def build_private_message(target: str, message: str) -> dict:
    return {"type": "private_message", "target": target, "message": message}

def build_get_rooms() -> dict:
    return {"type": "get_rooms"}

def build_get_pm_history(target: str) -> dict:
    return {"type": "get_pm_history", "target": target}

def build_get_users() -> dict:
    return {"type": "get_users"}

def build_get_friends() -> dict:
    return {"type": "get_friends"}

def build_add_friend(target: str) -> dict:
    return {"type": "add_friend", "target": target}

def build_remove_friend(target: str) -> dict:
    return {"type": "remove_friend", "target": target}

def build_get_pending_requests() -> dict:
    return {"type": "get_pending_requests"}

def build_accept_friend(target: str) -> dict:
    return {"type": "accept_friend", "target": target}

def build_decline_friend(target: str) -> dict:
    return {"type": "decline_friend", "target": target}
