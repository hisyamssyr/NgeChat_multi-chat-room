"""
server/database.py
------------------
Database Access Layer for the Multi-Chat Room Server.

Responsibilities:
  - Create and initialise all SQLite tables on first run.
  - Provide thread-safe CRUD operations for users, rooms, and messages.
  - Hash passwords with SHA-256 before storage (never store plaintext).

Thread safety:
  - A single threading.Lock (_lock) serialises every write operation.
  - SQLite is opened with check_same_thread=False so that the one
    connection object can be shared across ClientHandler threads.
  - All public methods acquire _lock for the duration of the call, which
    is safe because SQLite itself is not re-entered concurrently.

Extensibility notes:
  - To migrate to PostgreSQL/MySQL later, replace the sqlite3 calls here
    without touching any other module.
  - Message history is capped at HISTORY_LIMIT rows per room to avoid
    flooding newly-joined clients with thousands of old messages.
"""

import sqlite3
import hashlib
import threading
import logging
import os
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
    """
    Thread-safe SQLite database interface.

    Usage
    -----
        db = Database()          # uses default path
        db = Database("/custom/path/chat.db")
        db.initialise()          # must be called once before any other method
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        """
        Open the SQLite connection and create all tables if they do not
        already exist.  Must be called once before any other method.
        """
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

            cur.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT    UNIQUE NOT NULL,
                    password_hash TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rooms (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_name  TEXT    UNIQUE NOT NULL,
                    created_by TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_name TEXT    NOT NULL,
                    sender    TEXT    NOT NULL,
                    message   TEXT    NOT NULL,
                    timestamp TEXT    NOT NULL
                );
            """)
            self._conn.commit()
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
        """
        Register a new user account.

        Returns
        -------
        (True,  "Registration successful.")  on success
        (False, "<reason>")                  on failure
        """
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
        """
        Verify login credentials.

        Returns
        -------
        (True,  "Login successful.")  on success
        (False, "<reason>")           on failure
        """
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

    def create_room(self, room_name: str, created_by: str) -> tuple[bool, str]:
        """
        Persist a new chat room.

        Returns
        -------
        (True,  "Room '<name>' created.")  on success
        (False, "<reason>")                on failure
        """
        if not room_name or not room_name.strip():
            return False, "Room name cannot be empty."
        if len(room_name) > 64:
            return False, "Room name must be 64 characters or fewer."

        room_name = room_name.strip()

        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO rooms (room_name, created_by) VALUES (?, ?)",
                    (room_name, created_by),
                )
                self._conn.commit()
                logger.info("Room created: '%s' by %s", room_name, created_by)
                return True, f"Room '{room_name}' created."
            except sqlite3.IntegrityError:
                return False, f"Room '{room_name}' already exists."
            except sqlite3.Error as exc:
                logger.error("create_room DB error: %s", exc)
                return False, "Database error while creating room."

    def room_exists(self, room_name: str) -> bool:
        """Return True if the room exists in the database."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM rooms WHERE room_name = ?",
                (room_name.strip(),),
            ).fetchone()
            return row is not None

    def get_all_rooms(self) -> list[dict]:
        """
        Return a list of all rooms.

        Each entry is a dict: { "room_name": str, "created_by": str }
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT room_name, created_by FROM rooms ORDER BY room_name ASC"
            ).fetchall()
            return [{"room_name": r["room_name"], "created_by": r["created_by"]}
                    for r in rows]

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
        """
        Persist a broadcast message.

        Parameters
        ----------
        timestamp : optional ISO-8601 string; auto-generated (UTC) if None.

        Returns True on success, False on error.
        """
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
        """
        Fetch the most recent `limit` messages for a room, ordered oldest-first
        so the client can display them chronologically.

        Each entry is a dict:
            { "sender": str, "message": str, "timestamp": str }
        """
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
