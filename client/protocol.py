"""
client/protocol.py
------------------
Wire-protocol helpers for the Multi-Chat Room Client.

This module is intentionally a near-mirror of server/protocol.py.
Keeping them separate allows the client and server to evolve
independently (e.g. the client may add request signing, compression,
or a different logging setup without affecting the server copy).

Framing format (same as server):
    ┌────────────────────┬────────────────────────────────────┐
    │  4 bytes (uint32)  │  N bytes  (UTF-8 encoded JSON)     │
    │  big-endian length │  { "type": "...", ... }            │
    └────────────────────┴────────────────────────────────────┘

Packet builders (client → server):
    build_register(username, password)
    build_login(username, password)
    build_logout()
    build_create_room(room)
    build_join_room(room)
    build_leave_room(room)
    build_broadcast(room, message)
    build_private_message(target, message)
    build_get_rooms()
    build_get_users()
"""

import json
import struct
import logging

logger = logging.getLogger(__name__)

# ── Wire constants ────────────────────────────────────────────────────────────

_LENGTH_FORMAT = "!I"
_LENGTH_SIZE   = struct.calcsize(_LENGTH_FORMAT)   # == 4
MAX_PACKET_SIZE = 16 * 1024 * 1024                 # 16 MB guard

# ── Transport helpers ─────────────────────────────────────────────────────────

def send_packet(sock, data: dict) -> bool:
    """
    Serialise `data` to JSON and send it over `sock` with a 4-byte
    length prefix.

    Returns True on success, False on a broken connection.
    """
    try:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        header  = struct.pack(_LENGTH_FORMAT, len(payload))
        sock.sendall(header + payload)
        return True
    except (OSError, BrokenPipeError) as exc:
        logger.debug("send_packet failed: %s", exc)
        return False


def recv_packet(sock) -> dict | None:
    """
    Read exactly one framed packet from `sock`.

    Returns the parsed dict, or None if the server closed the connection
    or an unrecoverable error occurred.
    """
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


# ── Packet builders (client → server) ────────────────────────────────────────

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


def build_join_room(room: str) -> dict:
    """Create a join_room request packet."""
    return {"type": "join_room", "room": room}


def build_leave_room(room: str) -> dict:
    """Create a leave_room request packet."""
    return {"type": "leave_room", "room": room}


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
