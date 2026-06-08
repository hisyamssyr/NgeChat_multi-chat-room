"""Wire-protocol helpers for the Multi-Chat Room Server."""

import json
import struct
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Network byte order (big-endian) unsigned 32-bit integer — 4 bytes.
_LENGTH_FORMAT = "!I"
_LENGTH_SIZE   = struct.calcsize(_LENGTH_FORMAT)   # == 4

# Maximum allowed payload size (16 MB).  Guards against memory exhaustion.
MAX_PACKET_SIZE = 16 * 1024 * 1024

REQUIRED_FIELDS: dict[str, list[str]] = {
    "register":       ["username", "password"],
    "login":          ["username", "password"],
    "logout":         [],
    "create_room":    ["room"],
    "join_room":      ["room"],
    "join_by_code":   ["code"],
    "leave_room":     ["room"],
    "broadcast":      ["room", "message"],
    "private_message":["target", "message"],
    "get_rooms":      [],
    "get_users":      [],
}

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
        logger.warning("recv_packet: zero-length payload received, ignoring.")
        return {}
    if length > MAX_PACKET_SIZE:
        logger.error(
            "recv_packet: payload length %d exceeds MAX_PACKET_SIZE (%d). "
            "Dropping connection.",
            length,
            MAX_PACKET_SIZE,
        )
        return None

    raw = _recv_exactly(sock, length)
    if raw is None:
        return None

    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("recv_packet: JSON decode error — %s", exc)
        return {}   # return empty dict; caller will treat as unknown type

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
            # Remote end closed the connection cleanly.
            return None
        buf.extend(chunk)
    return bytes(buf)

def make_response(status: str, message: str, **extra: Any) -> dict:
    """Build a standard request-response packet."""
    return {"status": status, "message": message, **extra}

def make_broadcast_push(
    room: str,
    sender: str,
    message: str,
    timestamp: str,
) -> dict:
    """Outbound push: a room broadcast message."""
    return {
        "type":      "broadcast",
        "room":      room,
        "sender":    sender,
        "message":   message,
        "timestamp": timestamp,
    }

def make_private_push(sender: str, message: str, timestamp: str) -> dict:
    """Outbound push: a direct/private message."""
    return {
        "type":      "private_message",
        "sender":    sender,
        "message":   message,
        "timestamp": timestamp,
    }

def make_notification_push(room: str, message: str) -> dict:
    """Outbound push: a join/leave notification to room members."""
    return {
        "type":    "notification",
        "room":    room,
        "message": message,
    }

def make_history_packet(messages: list[dict]) -> dict:
    """Outbound: room message history on join."""
    return {
        "type":     "history",
        "messages": messages,
    }

def make_room_list_packet(rooms: list[dict]) -> dict:
    """Outbound: list of all rooms."""
    return {
        "type":  "room_list",
        "rooms": rooms,
    }

def make_user_list_packet(users: list[str]) -> dict:
    """Outbound: list of currently online usernames."""
    return {
        "type":  "user_list",
        "users": users,
    }

class PacketError(Exception):
    """Raised when a received packet fails validation."""

def validate_packet(packet: dict) -> str:
    """Validate that `packet` has a known type and all required fields."""
    if not isinstance(packet, dict):
        raise PacketError("Packet is not a JSON object.")

    ptype = packet.get("type")
    if not ptype:
        raise PacketError("Packet missing 'type' field.")

    if ptype not in REQUIRED_FIELDS:
        raise PacketError(f"Unknown packet type: '{ptype}'.")

    missing = [
        field for field in REQUIRED_FIELDS[ptype]
        if field not in packet or packet[field] is None
    ]
    if missing:
        raise PacketError(
            f"Packet type '{ptype}' missing required fields: {missing}."
        )

    return ptype
