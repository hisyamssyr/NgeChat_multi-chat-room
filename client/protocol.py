"""Wire-protocol helpers for the Multi-Chat Room Client."""

import json
import struct
import logging

logger = logging.getLogger(__name__)

_LENGTH_FORMAT = "!I"
_LENGTH_SIZE   = struct.calcsize(_LENGTH_FORMAT)   # == 4
MAX_PACKET_SIZE = 16 * 1024 * 1024                 # 16 MB guard

def send_packet(sock, data: dict) -> bool:
    """Serialise `data` to JSON and send it over `sock` with a 4-byte"""
    try:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        header  = struct.pack(_LENGTH_FORMAT, len(payload))
        sock.sendall(header + payload)
        return True
    except (OSError, BrokenPipeError) as exc:
        logger.debug("send_packet failed: %s", exc)
        return False

def recv_packet(sock) -> dict | None:
    """Read exactly one framed packet from `sock`."""
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
    """Read exactly `num_bytes` from `sock`, handling partial reads."""
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

def build_register(username: str, password: str) -> dict:
    """Create a register request packet."""
    return {"type": "register", "username": username, "password": password}

def build_login(username: str, password: str) -> dict:
    """Create a login request packet."""
    return {"type": "login", "username": username, "password": password}

def build_logout() -> dict:
    """Create a logout request packet."""
    return {"type": "logout"}

def build_create_room(room: str) -> dict:
    """Create a create_room request packet."""
    return {"type": "create_room", "room": room}

def build_join_room(room: str, code: str = "") -> dict:
    """Create a join_room request packet (for re-joining rooms you're already a member of)."""
    packet: dict = {"type": "join_room", "room": room}
    if code:
        packet["code"] = code
    return packet

def build_join_by_code(code: str) -> dict:
    """Join a room using only an 8-character invite code (no room name needed)."""
    return {"type": "join_by_code", "code": code.strip().upper()}

def build_leave_room(room: str) -> dict:
    """Create a leave_room request packet."""
    return {"type": "leave_room", "room": room}

def build_delete_room(room: str) -> dict:
    """Create a delete_room request packet (owner only)."""
    return {"type": "delete_room", "room": room}

def build_broadcast(room: str, message: str) -> dict:
    """Create a broadcast request packet."""
    return {"type": "broadcast", "room": room, "message": message}

def build_private_message(target: str, message: str) -> dict:
    """Create a private_message request packet."""
    return {"type": "private_message", "target": target, "message": message}

def build_get_rooms() -> dict:
    """Create a get_rooms request packet."""
    return {"type": "get_rooms"}

def build_get_users() -> dict:
    """Create a get_users request packet."""
    return {"type": "get_users"}
