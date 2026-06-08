"""
server/protocol.py
------------------
Wire-protocol helpers for the Multi-Chat Room Server.

Framing format (length-prefix):
    ┌────────────────────┬────────────────────────────────────┐
    │  4 bytes (uint32)  │  N bytes  (UTF-8 encoded JSON)     │
    │  big-endian length │  { "type": "...", ... }            │
    └────────────────────┴────────────────────────────────────┘

Why length-prefix instead of newline-delimited?
  - TCP is a byte stream; packet boundaries must be explicit.
  - Length-prefix is binary-safe: message text may contain newlines.
  - The same framing works for future binary payloads (file chunks,
    voice frames) — just extend the JSON envelope with a "data" field
    carrying base64-encoded bytes, or add a separate binary channel.

Packet validation:
  - Every incoming packet is validated against REQUIRED_FIELDS.
  - Malformed or unknown packets return an error response dict rather
    than raising, keeping the ClientHandler loop alive.

Extensibility:
  - To add TLS: wrap the socket before passing it here; send_packet /
    recv_packet work on any socket-like object that has .sendall() and
    .recv().
  - To add compression: add a 1-byte flags field after the 4-byte length
    and decompress in recv_packet when the flag is set.
"""

import json
import struct
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Wire constants ────────────────────────────────────────────────────────────

# Network byte order (big-endian) unsigned 32-bit integer — 4 bytes.
_LENGTH_FORMAT = "!I"
_LENGTH_SIZE   = struct.calcsize(_LENGTH_FORMAT)   # == 4

# Maximum allowed payload size (16 MB).  Guards against memory exhaustion.
MAX_PACKET_SIZE = 16 * 1024 * 1024

# ── Required fields per packet type ──────────────────────────────────────────

REQUIRED_FIELDS: dict[str, list[str]] = {
    "register":       ["username", "password"],
    "login":          ["username", "password"],
    "logout":         [],
    "create_room":    ["room"],
    "join_room":      ["room"],
    "leave_room":     ["room"],
    "broadcast":      ["room", "message"],
    "private_message":["target", "message"],
    "get_rooms":      [],
    "get_users":      [],
}

# ── Transport helpers ─────────────────────────────────────────────────────────

def send_packet(sock, data: dict) -> bool:
    """
    Serialise `data` to JSON and send it over `sock` with a 4-byte
    length prefix.

    Parameters
    ----------
    sock  : a connected socket (or TLS-wrapped socket)
    data  : dict — must be JSON-serialisable

    Returns
    -------
    True  on success
    False if the socket appears to be closed / broken
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

    Returns
    -------
    dict   — parsed JSON payload on success
    None   — if the connection was closed cleanly or an error occurred

    The caller should treat a None return as "client disconnected".
    """
    # ── 1. Read the 4-byte length header ─────────────────────────────────────
    header = _recv_exactly(sock, _LENGTH_SIZE)
    if header is None:
        return None

    (length,) = struct.unpack(_LENGTH_FORMAT, header)

    # ── 2. Guard against absurdly large payloads ──────────────────────────────
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

    # ── 3. Read the JSON body ─────────────────────────────────────────────────
    raw = _recv_exactly(sock, length)
    if raw is None:
        return None

    # ── 4. Decode JSON ────────────────────────────────────────────────────────
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("recv_packet: JSON decode error — %s", exc)
        return {}   # return empty dict; caller will treat as unknown type


def _recv_exactly(sock, num_bytes: int) -> bytes | None:
    """
    Read exactly `num_bytes` from `sock`, handling partial reads.

    Returns the bytes on success, or None if the connection was lost.
    """
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


# ── Packet builders (server → client) ────────────────────────────────────────

def make_response(status: str, message: str, **extra: Any) -> dict:
    """
    Build a standard request-response packet.

    Parameters
    ----------
    status  : "ok" or "error"
    message : human-readable string
    **extra : any additional fields to include (e.g. rooms=[...])

    Example
    -------
    make_response("ok", "Login successful.")
    make_response("error", "Room not found.")
    make_response("ok", "Room list.", rooms=[...])
    """
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


# ── Packet validation ─────────────────────────────────────────────────────────

class PacketError(Exception):
    """Raised when a received packet fails validation."""


def validate_packet(packet: dict) -> str:
    """
    Validate that `packet` has a known type and all required fields.

    Parameters
    ----------
    packet : dict returned by recv_packet()

    Returns
    -------
    The packet's "type" string on success.

    Raises
    ------
    PacketError  with a descriptive message on any validation failure.
    """
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
