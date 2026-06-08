    # server/database.py
    # ------------------
    # Database Access Layer for the Multi-Chat Room Server.
    # Responsibilities:
    # - Create and initialise all SQLite tables on first run.
    # - Provide thread-safe CRUD operations for users, rooms, and messages.
    # - Hash passwords with SHA-256 before storage (never store plaintext).
    # Thread safety:
    # - A single threading.Lock (_lock) serialises every write operation.
    # - SQLite is opened with check_same_thread=False so that the one
    # connection object can be shared across ClientHandler threads.
    # - All public methods acquire _lock for the duration of the call, which
    # is safe because SQLite itself is not re-entered concurrently.
    # Extensibility notes:
    # - To migrate to PostgreSQL/MySQL later, replace the sqlite3 calls here
    # without touching any other module.
    # - Message history is capped at HISTORY_LIMIT rows per room to avoid
    # flooding newly-joined clients with thousands of old messages.

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
        # Thread-safe SQLite database interface.
    # Usage
    # -----
    # db = Database()          # uses default path
    # db = Database("/custom/path/chat.db")
    # db.initialise()          # must be called once before any other method

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialise(self) -> None:
            # Open the SQLite connection and create all tables if they do not
    # already exist.  Must be called once before any other method.
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
            # Gracefully close the database connection.
        if self._conn:
            with self._lock:
                self._conn.close()
                self._conn = None
            logger.info("Database connection closed.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
            # Create schema tables (idempotent — safe to call on every start).
        with self._lock:
            cur = self._conn.cursor()

            cur.executescript("""
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
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (username, friend)
                );
            """)
            self._conn.commit()

            # ── Auto-migrations (safe to run every startup) ────────────────
            migrations = [
                "ALTER TABLE rooms ADD COLUMN invite_code TEXT NOT NULL DEFAULT ''",
                """CREATE TABLE IF NOT EXISTS friends (
                    username TEXT NOT NULL,
                    friend   TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (username, friend)
                )""",
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
            # Return a SHA-256 hex digest of the given plaintext password.
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def _now_utc() -> str:
            # Return the current UTC time as an ISO-8601 string.
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ------------------------------------------------------------------
    # User operations
    # ------------------------------------------------------------------

    def register_user(self, username: str, password: str) -> tuple[bool, str]:
            # Register a new user account.
    # Returns
    # -------
    # (True,  "Registration successful.")  on success
    # (False, "<reason>")                  on failure
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
            # Verify login credentials.
    # Returns
    # -------
    # (True,  "Login successful.")  on success
    # (False, "<reason>")           on failure
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
            # Return True if the username exists in the database.
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
            # Generate a cryptographically secure alphanumeric invite code.
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def create_room(self, room_name: str, created_by: str) -> tuple[bool, str, str]:
            # Create a new room, auto-generate an invite code, and make the
    # creator a permanent member.
    # Returns
    # -------
    # (True,  "Room '<name>' created.", plaintext_code)  on success
    # (False, "<reason>",               "")              on failure
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
                    "INSERT INTO rooms (room_name, created_by, invite_code)"
                    " VALUES (?, ?, ?)",
                    (room_name, created_by, invite_code),
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
            # Return True if the room exists in the database.
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM rooms WHERE room_name = ?",
                (room_name.strip(),),
            ).fetchone()
            return row is not None

    def is_room_member(self, room_name: str, username: str) -> bool:
            # Return True if `username` is a permanent member of `room_name`.
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM room_members WHERE room_name = ? AND username = ?",
                (room_name.strip(), username.strip()),
            ).fetchone()
            return row is not None

    def add_room_member(self, room_name: str, username: str) -> bool:
            # Add `username` as a permanent member of `room_name`. Idempotent.
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
        # Remove `username` permanently from `room_name`
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
        # Delete room, its members, and its messages (only if username is created_by).
        room_name = room_name.strip()
        username = username.strip()
        with self._lock:
            # Check ownership
            row = self._conn.execute(
                "SELECT created_by FROM rooms WHERE room_name = ?",
                (room_name,)
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
            # Verify whether `code` matches the invite code for `room_name`.
    # Returns True if correct, False if wrong or room doesn't exist.
        with self._lock:
            row = self._conn.execute(
                "SELECT invite_code FROM rooms WHERE room_name = ?",
                (room_name.strip(),),
            ).fetchone()

        if row is None:
            return False
        return code.strip().upper() == row["invite_code"]

    def get_all_rooms(self, username: str = "") -> list[dict]:
            # Return rooms the user is a member of (or all rooms if no username given).
    # Each entry: { "room_name": str, "created_by": str, "is_member": bool }
        with self._lock:
            if username:
                # Only rooms where the user is a member.
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
            # Look up the room name whose invite code matches `code`.
    # Returns the room_name string on success, or None if no room matches.
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
            # Persist a broadcast message.
    # Parameters
    # ----------
    # timestamp : optional ISO-8601 string; auto-generated (UTC) if None.
    # Returns True on success, False on error.
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
        # Fetch the most recent `limit` messages for a room, ordered oldest-first
        # so the client can display them chronologically.
        # Each entry is a dict:
        # { "sender": str, "message": str, "timestamp": str }
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

    def add_friend(self, username: str, friend: str) -> tuple[bool, str]:
        # Add `friend` to `username`'s friend list.
        if username == friend:
            return False, "You cannot add yourself as a friend."
        if not self.user_exists(friend):
            return False, f"User '{friend}' does not exist."
        now = self._now_utc()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO friends (username, friend, added_at) VALUES (?, ?, ?)",
                    (username, friend, now),
                )
                self._conn.commit()
                return True, f"'{friend}' added to your friends."
            except sqlite3.IntegrityError:
                return False, f"'{friend}' is already in your friends list."
            except sqlite3.Error as exc:
                logger.error("add_friend DB error: %s", exc)
                return False, "Database error."

    def remove_friend(self, username: str, friend: str) -> tuple[bool, str]:
        # Remove `friend` from `username`'s friend list.
        with self._lock:
            try:
                cur = self._conn.execute(
                    "DELETE FROM friends WHERE username = ? AND friend = ?",
                    (username, friend),
                )
                self._conn.commit()
                if cur.rowcount == 0:
                    return False, f"'{friend}' is not in your friends list."
                return True, f"'{friend}' removed from your friends."
            except sqlite3.Error as exc:
                logger.error("remove_friend DB error: %s", exc)
                return False, "Database error."

    def get_friends(self, username: str) -> list[str]:
        # Return sorted list of friend usernames for `username`.
        with self._lock:
            rows = self._conn.execute(
                "SELECT friend FROM friends WHERE username = ? ORDER BY friend ASC",
                (username,),
            ).fetchall()
            return [r["friend"] for r in rows]

    def is_friend(self, username: str, friend: str) -> bool:
        # Return True if `friend` is in `username`'s friend list.
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM friends WHERE username = ? AND friend = ?",
                (username, friend),
            ).fetchone()
            return row is not None
