"""Wire-protocol helpers shared between server modules."""

import json
import logging
import struct
from typing import Any

logger = logging.getLogger(__name__)

# 4-byte big-endian length prefix used on every packet.
_LENGTH_FORMAT = "!I"
_LENGTH_SIZE = struct.calcsize(_LENGTH_FORMAT)

# Guards against memory exhaustion from a misbehaving/malicious client.
MAX_PACKET_SIZE = 16 * 1024 * 1024

REQUIRED_FIELDS: dict[str, list[str]] = {
    "register": ["username", "password"],
    "login": ["username", "password"],
    "logout": [],
    "create_room": ["room"],
    "join_room": ["room"],
    "join_by_code": ["code"],
    "leave_room": ["room"],
    "broadcast": ["room", "message"],
    "private_message": ["target", "message"],
    "get_rooms": [],
    "get_users": [],
    "delete_room": ["room"],
    "add_friend": ["target"],
    "remove_friend": ["target"],
    "get_friends": [],
    "accept_friend": ["target"],
    "decline_friend": ["target"],
    "get_pending_requests": [],
    "get_pm_history": ["target"],
    "file_transfer": ["scope", "filename", "data"],
    "reaction": ["scope", "message_id", "emoji"],
}


def send_packet(sock, data: dict) -> bool:
    """Serialise *data* to JSON and send it with a 4-byte length prefix."""
    try:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        sock.sendall(struct.pack(_LENGTH_FORMAT, len(payload)) + payload)
        return True
    except (OSError, BrokenPipeError) as exc:
        logger.debug("send_packet failed: %s", exc)
        return False


def recv_packet(sock) -> dict | None:
    """Read one framed packet; returns None on connection close or error."""
    header = _recv_exactly(sock, _LENGTH_SIZE)
    if header is None:
        return None

    (length,) = struct.unpack(_LENGTH_FORMAT, header)

    if length == 0:
        logger.warning("recv_packet: zero-length payload, ignoring.")
        return {}
    if length > MAX_PACKET_SIZE:
        logger.error(
            "recv_packet: payload length %d exceeds MAX_PACKET_SIZE (%d). Dropping connection.",
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
        return {}  # caller treats unknown type as a no-op


def _recv_exactly(sock, num_bytes: int) -> bytes | None:
    """Read exactly *num_bytes* bytes, handling partial TCP reads."""
    buf = bytearray()
    while len(buf) < num_bytes:
        try:
            chunk = sock.recv(num_bytes - len(buf))
        except OSError as exc:
            logger.debug("_recv_exactly OSError: %s", exc)
            return None
        if not chunk:
            return None  # clean close by remote
        buf.extend(chunk)
    return bytes(buf)


def make_response(status: str, message: str, **extra: Any) -> dict:
    return {"status": status, "message": message, **extra}


def make_broadcast_push(
    room: str,
    sender: str,
    message: str,
    timestamp: str,
    message_id: str | None = None,
) -> dict:
    packet = {
        "type": "broadcast",
        "room": room,
        "sender": sender,
        "message": message,
        "timestamp": timestamp,
    }
    if message_id:
        packet["message_id"] = message_id
    return packet


def make_private_push(
    sender: str,
    target: str,
    message: str,
    timestamp: str,
    message_id: str,
) -> dict:
    return {
        "type": "private_message",
        "sender": sender,
        "target": target,
        "message": message,
        "timestamp": timestamp,
        "message_id": message_id,
    }


def make_notification_push(room: str, message: str) -> dict:
    return {"type": "notification", "room": room, "message": message}


def make_history_packet(room: str, messages: list[dict]) -> dict:
    return {"type": "history", "room": room, "messages": messages}


def make_room_list_packet(rooms: list[dict]) -> dict:
    return {"type": "room_list", "rooms": rooms}


def make_user_list_packet(users: list[str]) -> dict:
    return {"type": "user_list", "users": users}


def make_friend_list_packet(friends: list[dict]) -> dict:
    return {"type": "friend_list", "friends": friends}


def make_friend_request_push(from_user: str) -> dict:
    return {"type": "friend_request", "from": from_user}


def make_pending_requests_list(requests: list[str]) -> dict:
    return {"type": "pending_requests_list", "requests": requests}


def make_file_transfer_push(
    *,
    scope: str,
    sender: str,
    filename: str,
    data: str,
    timestamp: str,
    size: int,
    kind: str = "file",
    message_id: str | None = None,
    room: str | None = None,
    target: str | None = None,
) -> dict:
    packet = {
        "type": "file_transfer",
        "scope": scope,
        "sender": sender,
        "filename": filename,
        "data": data,
        "timestamp": timestamp,
        "size": size,
        "kind": kind,
    }
    if message_id:
        packet["message_id"] = message_id
    if room:
        packet["room"] = room
    if target:
        packet["target"] = target
    return packet


def make_reaction_push(
    *,
    scope: str,
    sender: str,
    message_id: str,
    emoji: str,
    timestamp: str,
    action: str = "set",
    reactions: list[dict] | None = None,
    room: str | None = None,
    target: str | None = None,
) -> dict:
    packet = {
        "type": "reaction",
        "scope": scope,
        "sender": sender,
        "message_id": message_id,
        "emoji": emoji,
        "action": action,
        "timestamp": timestamp,
        "reactions": reactions or [],
    }
    if room:
        packet["room"] = room
    if target:
        packet["target"] = target
    return packet


class PacketError(Exception):
    """Raised when a received packet fails validation."""


def validate_packet(packet: dict) -> str:
    """Return the packet type string, or raise PacketError."""
    if not isinstance(packet, dict):
        raise PacketError("Packet is not a JSON object.")

    ptype = packet.get("type")
    if not ptype:
        raise PacketError("Packet missing 'type' field.")

    if ptype not in REQUIRED_FIELDS:
        raise PacketError(f"Unknown packet type: '{ptype}'.")

    missing = [
        field
        for field in REQUIRED_FIELDS[ptype]
        if field not in packet or packet[field] is None
    ]
    if missing:
        raise PacketError(f"Packet type '{ptype}' missing required fields: {missing}.")

    return ptype
