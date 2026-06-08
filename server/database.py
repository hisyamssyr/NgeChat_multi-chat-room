"""Database Access Layer for the Multi-Chat Room Server."""

import sqlite3
import hashlib
import threading
import logging
import os
import secrets
import string
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Maximum number of historical messages sent to a client on room join.
HISTORY_LIMIT = 50

# Resolved at import time so server.py can control the DB path.
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database",
    "chat.db",
)

class Database:
    """Thread-safe SQLite database interface."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        """Open the SQLite connection and create all tables if they do not"""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,   # we guard access with _lock
        )
        self._conn.row_factory = sqlite3.Row  # allow column-name access
        self._conn.execute("PRAGMA journal_mode=WAL;")   # better concurrency
        self._conn.execute("PRAGMA foreign_keys=ON;")

        self._create_tables()
        logger.info("Database initialised at %s", self._db_path)

    def close(self) -> None:
        """Gracefully close the database connection."""
        if self._conn:
            with self._lock:
                self._conn.close()
                self._conn = None
            logger.info("Database connection closed.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """Create schema tables (idempotent — safe to call on every start)."""
        with self._lock:
            cur = self._conn.cursor()

            cur.executescript("""CREATE TABLE IF NOT EXISTS users (""")
            self._conn.commit()

            migrations = [
                "ALTER TABLE rooms ADD COLUMN invite_hash TEXT NOT NULL DEFAULT ''",
                # Drop old password_hash col: SQLite doesn’t support DROP COLUMN
                # before 3.35, so we just ignore it if it exists.
            ]
            for sql in migrations:
                try:
                    self._conn.execute(sql)
                    self._conn.commit()
                    logger.info("DB migration applied: %s", sql[:60])
                except Exception:
                    pass   # column / table already exists

        logger.debug("Database tables verified / created.")

    @staticmethod
    def _hash_password(password: str) -> str:
        """Return a SHA-256 hex digest of the given plaintext password."""
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def _now_utc() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ------------------------------------------------------------------
    # User operations
    # ------------------------------------------------------------------

    def register_user(self, username: str, password: str) -> tuple[bool, str]:
        """Register a new user account."""
        if not username or not username.strip():
            return False, "Username cannot be empty."
        if not password:
            return False, "Password cannot be empty."
        if len(username) > 32:
            return False, "Username must be 32 characters or fewer."

        username = username.strip()
        password_hash = self._hash_password(password)

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
                self._conn.commit()
                logger.info("New user registered: %s", username)
                return True, "Registration successful."
            except sqlite3.IntegrityError:
                return False, f"Username '{username}' is already taken."
            except sqlite3.Error as exc:
                logger.error("register_user DB error: %s", exc)
                return False, "Database error during registration."

    def validate_login(self, username: str, password: str) -> tuple[bool, str]:
        """Verify login credentials."""
        if not username or not password:
            return False, "Username and password are required."

        password_hash = self._hash_password(password)

        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT password_hash FROM users WHERE username = ?",
                    (username.strip(),),
                ).fetchone()

                if row is None:
                    return False, "User not found."
                if row["password_hash"] != password_hash:
                    return False, "Incorrect password."
                return True, "Login successful."
            except sqlite3.Error as exc:
                logger.error("validate_login DB error: %s", exc)
                return False, "Database error during login."

    def user_exists(self, username: str) -> bool:
        """Return True if the username exists in the database."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM users WHERE username = ?",
                (username.strip(),),
            ).fetchone()
            return row is not None

    # ------------------------------------------------------------------
    # Room operations
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_invite_code(length: int = 8) -> str:
        """Generate a cryptographically secure alphanumeric invite code."""
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def create_room(self, room_name: str, created_by: str) -> tuple[bool, str, str]:
        """Create a new room, auto-generate an invite code, and make the"""
        if not room_name or not room_name.strip():
            return False, "Room name cannot be empty.", ""
        if len(room_name) > 64:
            return False, "Room name must be 64 characters or fewer.", ""

        room_name   = room_name.strip()
        invite_code = self._generate_invite_code()
        invite_hash = self._hash_password(invite_code)   # reuse SHA-256 helper
        now         = self._now_utc()

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO rooms (room_name, created_by, invite_hash)"
                    " VALUES (?, ?, ?)",
                    (room_name, created_by, invite_hash),
                )
                # Creator is automatically a member.
                self._conn.execute(
                    "INSERT OR IGNORE INTO room_members (room_name, username, joined_at)"
                    " VALUES (?, ?, ?)",
                    (room_name, created_by, now),
                )
                self._conn.commit()
                logger.info(
                    "Room created: '%s' by %s (code=%s)",
                    room_name, created_by, invite_code,
                )
                return True, f"Room '{room_name}' created.", invite_code
            except sqlite3.IntegrityError:
                return False, f"Room '{room_name}' already exists.", ""
            except sqlite3.Error as exc:
                logger.error("create_room DB error: %s", exc)
                return False, "Database error while creating room.", ""

    def room_exists(self, room_name: str) -> bool:
        """Return True if the room exists in the database."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM rooms WHERE room_name = ?",
                (room_name.strip(),),
            ).fetchone()
            return row is not None

    def is_room_member(self, room_name: str, username: str) -> bool:
        """Return True if `username` is a permanent member of `room_name`."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM room_members WHERE room_name = ? AND username = ?",
                (room_name.strip(), username.strip()),
            ).fetchone()
            return row is not None

    def add_room_member(self, room_name: str, username: str) -> bool:
        """Add `username` as a permanent member of `room_name`."""
        now = self._now_utc()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR IGNORE INTO room_members (room_name, username, joined_at)"
                    " VALUES (?, ?, ?)",
                    (room_name.strip(), username.strip(), now),
                )
                self._conn.commit()
                return True
            except sqlite3.Error as exc:
                logger.error("add_room_member DB error: %s", exc)
                return False

    def check_room_code(self, room_name: str, code: str) -> bool:
        """Verify whether `code` matches the invite code for `room_name`."""
        with self._lock:
            row = self._conn.execute(
                "SELECT invite_hash FROM rooms WHERE room_name = ?",
                (room_name.strip(),),
            ).fetchone()

        if row is None:
            return False
        return self._hash_password(code.strip()) == row["invite_hash"]

    def get_all_rooms(self, username: str = "") -> list[dict]:
        """Return rooms the user is a member of (or all rooms if no username given)."""
        with self._lock:
            if username:
                # Only rooms where the user is a member.
                rows = self._conn.execute(
                    "SELECT r.room_name, r.created_by, 1 AS is_member"
                    " FROM rooms r"
                    " JOIN room_members m ON m.room_name = r.room_name"
                    " WHERE m.username = ?"
                    " ORDER BY r.room_name ASC",
                    (username,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT room_name, created_by, 0 AS is_member"
                    " FROM rooms ORDER BY room_name ASC"
                ).fetchall()

            return [
                {
                    "room_name":  r["room_name"],
                    "created_by": r["created_by"],
                    "is_member":  bool(r["is_member"]),
                }
                for r in rows
            ]

    def get_room_by_code(self, code: str) -> str | None:
        """Look up the room name whose invite code matches `code`."""
        code_hash = self._hash_password(code.strip().upper())
        with self._lock:
            row = self._conn.execute(
                "SELECT room_name FROM rooms WHERE invite_hash = ?",
                (code_hash,),
            ).fetchone()
        return row["room_name"] if row else None

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    def save_message(
        self,
        room_name: str,
        sender: str,
        message: str,
        timestamp: str | None = None,
    ) -> bool:
        """Persist a broadcast message."""
        if timestamp is None:
            timestamp = self._now_utc()

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO messages (room_name, sender, message, timestamp)"
                    " VALUES (?, ?, ?, ?)",
                    (room_name, sender, message, timestamp),
                )
                self._conn.commit()
                return True
            except sqlite3.Error as exc:
                logger.error("save_message DB error: %s", exc)
                return False

    def get_room_history(self, room_name: str, limit: int = HISTORY_LIMIT) -> list[dict]:
        """Fetch the most recent `limit` messages for a room, ordered oldest-first"""
        with self._lock:
            rows = self._conn.execute(
                """SELECT sender, message, timestamp""",
                (room_name, limit),
            ).fetchall()
            return [
                {
                    "sender":    r["sender"],
                    "message":   r["message"],
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]
