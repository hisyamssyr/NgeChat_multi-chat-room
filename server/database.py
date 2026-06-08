import sqlite3
import hashlib
import threading
import logging
import os
import secrets
import string
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 50

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database",
    "chat.db",
)


class Database:
    """Thread-safe SQLite interface for the chat server.

    A single threading.Lock serialises every write so the one connection
    object can be shared safely across ClientHandler threads
    (check_same_thread=False).
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,  # guarded by _lock
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")  # better concurrency under load
        self._conn.execute("PRAGMA foreign_keys=ON;")

        self._create_tables()
        logger.info("Database initialised at %s", self._db_path)

    def close(self) -> None:
        if self._conn:
            with self._lock:
                self._conn.close()
                self._conn = None
            logger.info("Database connection closed.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        with self._lock:
            self._conn.cursor().executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT    UNIQUE NOT NULL,
                    password_hash TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rooms (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_name     TEXT    UNIQUE NOT NULL,
                    created_by    TEXT    NOT NULL,
                    invite_code   TEXT    NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS room_members (
                    room_name TEXT NOT NULL,
                    username  TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (room_name, username)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_name TEXT    NOT NULL,
                    sender    TEXT    NOT NULL,
                    message   TEXT    NOT NULL,
                    timestamp TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS friends (
                    username TEXT NOT NULL,
                    friend   TEXT NOT NULL,
                    status   TEXT NOT NULL DEFAULT 'pending',
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (username, friend)
                );
            """)
            self._conn.commit()

            # Safe to run every startup — each statement is idempotent or will
            # silently fail if the column/table already exists.
            migrations = [
                "ALTER TABLE rooms ADD COLUMN invite_code TEXT NOT NULL DEFAULT ''",
                """CREATE TABLE IF NOT EXISTS friends (
                    username TEXT NOT NULL,
                    friend   TEXT NOT NULL,
                    status   TEXT NOT NULL DEFAULT 'pending',
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (username, friend)
                )""",
                # SQLite < 3.35 does not support DROP COLUMN; adding the status
                # column to existing databases is the only migration needed here.
                "ALTER TABLE friends ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'",
            ]
            for sql in migrations:
                try:
                    self._conn.execute(sql)
                    self._conn.commit()
                    logger.info("DB migration applied: %s", sql[:60])
                except Exception:
                    pass  # column / table already exists

        logger.debug("Database tables verified / created.")

    @staticmethod
    def _hash_password(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def _now_utc() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ------------------------------------------------------------------
    # User operations
    # ------------------------------------------------------------------

    def register_user(self, username: str, password: str) -> tuple[bool, str]:
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
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def create_room(self, room_name: str, created_by: str) -> tuple[bool, str, str]:
        if not room_name or not room_name.strip():
            return False, "Room name cannot be empty.", ""
        if len(room_name) > 64:
            return False, "Room name must be 64 characters or fewer.", ""

        room_name   = room_name.strip()
        invite_code = self._generate_invite_code()
        now         = self._now_utc()

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO rooms (room_name, created_by, invite_code) VALUES (?, ?, ?)",
                    (room_name, created_by, invite_code),
                )
                # Creator is automatically a permanent member.
                self._conn.execute(
                    "INSERT OR IGNORE INTO room_members (room_name, username, joined_at)"
                    " VALUES (?, ?, ?)",
                    (room_name, created_by, now),
                )
                self._conn.commit()
                logger.info("Room created: '%s' by %s (code=%s)", room_name, created_by, invite_code)
                return True, f"Room '{room_name}' created.", invite_code
            except sqlite3.IntegrityError:
                return False, f"Room '{room_name}' already exists.", ""
            except sqlite3.Error as exc:
                logger.error("create_room DB error: %s", exc)
                return False, "Database error while creating room.", ""

    def room_exists(self, room_name: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM rooms WHERE room_name = ?",
                (room_name.strip(),),
            ).fetchone()
            return row is not None

    def is_room_member(self, room_name: str, username: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM room_members WHERE room_name = ? AND username = ?",
                (room_name.strip(), username.strip()),
            ).fetchone()
            return row is not None

    def add_room_member(self, room_name: str, username: str) -> bool:
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

    def remove_room_member(self, room_name: str, username: str) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM room_members WHERE room_name = ? AND username = ?",
                    (room_name.strip(), username.strip()),
                )
                self._conn.commit()
                return True
            except sqlite3.Error as exc:
                logger.error("remove_room_member DB error: %s", exc)
                return False

    def delete_room(self, room_name: str, username: str) -> tuple[bool, str]:
        room_name = room_name.strip()
        username  = username.strip()
        with self._lock:
            row = self._conn.execute(
                "SELECT created_by FROM rooms WHERE room_name = ?",
                (room_name,),
            ).fetchone()

            if not row:
                return False, f"Room '{room_name}' does not exist."
            if row["created_by"] != username:
                return False, "Only the room owner can delete this room."

            try:
                self._conn.execute("DELETE FROM rooms WHERE room_name = ?", (room_name,))
                self._conn.execute("DELETE FROM room_members WHERE room_name = ?", (room_name,))
                self._conn.execute("DELETE FROM messages WHERE room_name = ?", (room_name,))
                self._conn.commit()
                logger.info("Room deleted permanently: '%s' by %s", room_name, username)
                return True, f"Room '{room_name}' has been permanently deleted."
            except sqlite3.Error as exc:
                logger.error("delete_room DB error: %s", exc)
                return False, "Database error during room deletion."

    def check_room_code(self, room_name: str, code: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT invite_code FROM rooms WHERE room_name = ?",
                (room_name.strip(),),
            ).fetchone()

        if row is None:
            return False
        return code.strip().upper() == row["invite_code"]

    def get_all_rooms(self, username: str = "") -> list[dict]:
        with self._lock:
            if username:
                rows = self._conn.execute(
                    "SELECT r.room_name, r.created_by, r.invite_code, 1 AS is_member"
                    " FROM rooms r"
                    " JOIN room_members m ON m.room_name = r.room_name"
                    " WHERE m.username = ?"
                    " ORDER BY r.room_name ASC",
                    (username,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT room_name, created_by, invite_code, 0 AS is_member"
                    " FROM rooms ORDER BY room_name ASC"
                ).fetchall()

            return [
                {
                    "room_name":   r["room_name"],
                    "created_by":  r["created_by"],
                    "invite_code": r["invite_code"],
                    "is_member":   bool(r["is_member"]),
                }
                for r in rows
            ]

    def get_room_by_code(self, code: str) -> str | None:
        code = code.strip().upper()
        with self._lock:
            row = self._conn.execute(
                "SELECT room_name FROM rooms WHERE invite_code = ?",
                (code,),
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
        # Fetch the most recent `limit` messages ordered oldest-first so the
        # client can render them chronologically without reversing the list.
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT sender, message, timestamp
                FROM (
                    SELECT id, sender, message, timestamp
                    FROM   messages
                    WHERE  room_name = ?
                    ORDER  BY id DESC
                    LIMIT  ?
                )
                ORDER BY id ASC
                """,
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

    # ------------------------------------------------------------------
    # Friend operations
    # ------------------------------------------------------------------

    def send_friend_request(self, username: str, friend: str) -> tuple[bool, str]:
        if username == friend:
            return False, "You cannot add yourself as a friend."
        if not self.user_exists(friend):
            return False, f"User '{friend}' does not exist."

        now = self._now_utc()
        with self._lock:
            # Block duplicate requests in either direction before attempting insert.
            row = self._conn.execute(
                "SELECT status FROM friends WHERE (username = ? AND friend = ?)"
                " OR (username = ? AND friend = ?)",
                (username, friend, friend, username),
            ).fetchone()
            if row:
                if row["status"] == "accepted":
                    return False, f"You are already friends with '{friend}'."
                return False, f"A friend request with '{friend}' already exists."
            try:
                self._conn.execute(
                    "INSERT INTO friends (username, friend, status, added_at)"
                    " VALUES (?, ?, 'pending', ?)",
                    (username, friend, now),
                )
                self._conn.commit()
                return True, f"Friend request sent to '{friend}'."
            except sqlite3.IntegrityError:
                return False, "A friend request already exists."
            except sqlite3.Error as exc:
                logger.error("send_friend_request DB error: %s", exc)
                return False, "Database error."

    def accept_friend_request(self, username: str, requester: str) -> tuple[bool, str]:
        now = self._now_utc()
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM friends WHERE username = ? AND friend = ?",
                (requester, username),
            ).fetchone()
            if not row or row["status"] != "pending":
                return False, f"No pending request from '{requester}'."
            try:
                self._conn.execute(
                    "UPDATE friends SET status = 'accepted' WHERE username = ? AND friend = ?",
                    (requester, username),
                )
                # Insert the reverse row so both sides appear in each other's list.
                self._conn.execute(
                    "INSERT OR IGNORE INTO friends (username, friend, status, added_at)"
                    " VALUES (?, ?, 'accepted', ?)",
                    (username, requester, now),
                )
                self._conn.commit()
                return True, f"You are now friends with '{requester}'."
            except sqlite3.Error as exc:
                logger.error("accept_friend_request DB error: %s", exc)
                return False, "Database error."

    def decline_friend_request(self, username: str, requester: str) -> tuple[bool, str]:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM friends WHERE username = ? AND friend = ? AND status = 'pending'",
                (requester, username),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return False, f"No pending request from '{requester}'."
            return True, f"Friend request from '{requester}' declined."

    def remove_friend(self, username: str, friend: str) -> tuple[bool, str]:
        # Deletes both directions so neither user sees the other anymore.
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM friends WHERE (username = ? AND friend = ?)"
                    " OR (username = ? AND friend = ?)",
                    (username, friend, friend, username),
                )
                self._conn.commit()
                return True, f"'{friend}' removed from your friends."
            except sqlite3.Error as exc:
                logger.error("remove_friend DB error: %s", exc)
                return False, "Database error."

    def get_friends(self, username: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT friend FROM friends WHERE username = ? AND status = 'accepted'"
                " ORDER BY friend ASC",
                (username,),
            ).fetchall()
            return [r["friend"] for r in rows]

    def get_pending_sent(self, username: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT friend FROM friends WHERE username = ? AND status = 'pending'"
                " ORDER BY friend ASC",
                (username,),
            ).fetchall()
            return [r["friend"] for r in rows]

    def is_friend(self, username: str, friend: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM friends WHERE username = ? AND friend = ? AND status = 'accepted'",
                (username, friend),
            ).fetchone()
            return row is not None
