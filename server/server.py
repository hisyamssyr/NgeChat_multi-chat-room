"""
server/server.py
----------------
Multi-Chat Room Server — Main Entry Point.

Architecture
------------
  Main Thread:
    • Binds a TCP socket and enters an accept() loop.
    • For each incoming connection, spawns a ClientHandler thread
      (daemon=True so they die automatically if the server exits).

  ClientHandler Thread (one per connected client):
    • Owns the client socket for its lifetime.
    • Runs a recv_packet() loop — blocks until a packet arrives.
    • Dispatches to the appropriate handler method.
    • On any exception or clean disconnect, calls _cleanup() which
      removes the user from RoomManager and notifies their rooms.

  Shared singletons (created once, passed by reference):
    • db   : Database   — persists users, rooms, messages.
    • rooms: RoomManager — tracks online users and memberships.

Threading safety:
    • Database  uses threading.Lock  (in database.py).
    • RoomManager uses threading.RLock (in room_manager.py).
    • ClientHandler itself holds no mutable state of its own;
      everything is delegated to the two singletons above.

Signal handling:
    • SIGINT / KeyboardInterrupt triggers a graceful shutdown:
      closes the server socket (breaks accept loop) and calls db.close().

Extensibility:
    • TLS:  wrap `client_sock` with ssl.wrap_socket() before passing
            to ClientHandler.__init__().
    • IPv6: change AF_INET → AF_INET6; bind to "::" instead of "".
"""

import socket
import threading
import logging
import sys
import os

# ── Make `server/` importable as a package from the project root ──────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.logger      import setup_logger
from server.database    import Database
from server.room_manager import RoomManager
from server.protocol    import (
    recv_packet,
    send_packet,
    validate_packet,
    PacketError,
    make_response,
    make_broadcast_push,
    make_private_push,
    make_notification_push,
    make_history_packet,
    make_room_list_packet,
    make_user_list_packet,
)

# ── Server configuration (override with env vars if desired) ──────────────────
HOST        = os.environ.get("CHAT_HOST", "0.0.0.0")
PORT        = int(os.environ.get("CHAT_PORT", "9090"))
BACKLOG     = 10      # max queued connections before accept()
RECV_TIMEOUT = 300    # seconds of silence before the server pings-out a client

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ClientHandler — one instance per connected TCP client
# ─────────────────────────────────────────────────────────────────────────────

class ClientHandler:
    """
    Manages the full lifecycle of a single client connection.

    Lifecycle:
        __init__  →  run()  →  _handle_packet()  →  _cleanup()
                                      ↓
                         one of the _handle_* methods
    """

    def __init__(
        self,
        client_sock: socket.socket,
        client_addr: tuple,
        db: Database,
        rooms: RoomManager,
    ) -> None:
        self._sock      = client_sock
        self._addr      = client_addr
        self._db        = db
        self._rooms     = rooms
        self._username: str | None = None   # None until successful login
        self._running   = True

    # ------------------------------------------------------------------
    # Main receive loop (runs in its own thread)
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Entry point called by the spawned thread.
        Loops on recv_packet() until the client disconnects or an error
        occurs, then calls _cleanup().
        """
        logger.info("New connection from %s:%d", *self._addr)
        try:
            while self._running:
                packet = recv_packet(self._sock)

                if packet is None:
                    # Client closed the connection.
                    logger.info(
                        "Client %s:%d disconnected.",
                        *self._addr,
                    )
                    break

                if not packet:
                    # Empty / malformed JSON — send error and continue.
                    send_packet(self._sock, make_response("error", "Empty or malformed packet."))
                    continue

                self._handle_packet(packet)

        except Exception as exc:
            logger.error(
                "Unhandled exception in ClientHandler for %s:%d — %s",
                *self._addr, exc,
                exc_info=True,
            )
        finally:
            self._cleanup()

    # ------------------------------------------------------------------
    # Packet dispatch
    # ------------------------------------------------------------------

    def _handle_packet(self, packet: dict) -> None:
        """
        Validate and dispatch a single incoming packet to the correct
        handler method.  Errors are caught and sent back to the client.
        """
        try:
            ptype = validate_packet(packet)
        except PacketError as exc:
            send_packet(self._sock, make_response("error", str(exc)))
            logger.warning(
                "PacketError from %s:%d — %s",
                *self._addr, exc,
            )
            return

        # Route to handler
        dispatch = {
            "register":        self._handle_register,
            "login":           self._handle_login,
            "logout":          self._handle_logout,
            "create_room":     self._handle_create_room,
            "join_room":       self._handle_join_room,
            "leave_room":      self._handle_leave_room,
            "broadcast":       self._handle_broadcast,
            "private_message": self._handle_private_message,
            "get_rooms":       self._handle_get_rooms,
            "get_users":       self._handle_get_users,
        }
        handler = dispatch.get(ptype)
        if handler:
            handler(packet)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_login(self) -> bool:
        """
        Send an error if not authenticated.
        Returns True if logged in, False otherwise.
        """
        if self._username is None:
            send_packet(
                self._sock,
                make_response("error", "You must be logged in to do that."),
            )
            return False
        return True

    def _send_ok(self, message: str, **extra) -> None:
        send_packet(self._sock, make_response("ok", message, **extra))

    def _send_err(self, message: str) -> None:
        send_packet(self._sock, make_response("error", message))

    # ------------------------------------------------------------------
    # Handler: register
    # ------------------------------------------------------------------

    def _handle_register(self, packet: dict) -> None:
        username = packet["username"].strip()
        password = packet["password"]

        ok, msg = self._db.register_user(username, password)
        if ok:
            self._send_ok(msg)
            logger.info("Registered new user: %s", username)
        else:
            self._send_err(msg)

    # ------------------------------------------------------------------
    # Handler: login
    # ------------------------------------------------------------------

    def _handle_login(self, packet: dict) -> None:
        username = packet["username"].strip()
        password = packet["password"]

        # Reject if already logged in on this connection.
        if self._username is not None:
            self._send_err(f"Already logged in as '{self._username}'.")
            return

        # Reject if that username is already logged in elsewhere.
        if self._rooms.is_online(username):
            self._send_err(
                f"'{username}' is already logged in from another session."
            )
            return

        ok, msg = self._db.validate_login(username, password)
        if not ok:
            self._send_err(msg)
            return

        # Success — register as online.
        self._username = username
        self._rooms.add_user(username, self._sock)
        self._send_ok(msg)
        logger.info("User logged in: %s from %s:%d", username, *self._addr)

    # ------------------------------------------------------------------
    # Handler: logout
    # ------------------------------------------------------------------

    def _handle_logout(self, packet: dict) -> None:
        if not self._require_login():
            return

        username = self._username
        self._running = False   # stop the recv loop after this
        self._send_ok("Logged out successfully.")
        logger.info("User logged out: %s", username)
        # _cleanup() will run in the finally block of run()

    # ------------------------------------------------------------------
    # Handler: create_room
    # ------------------------------------------------------------------

    def _handle_create_room(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()
        ok, msg = self._db.create_room(room_name, self._username)
        if ok:
            self._send_ok(msg)
        else:
            self._send_err(msg)

    # ------------------------------------------------------------------
    # Handler: join_room
    # ------------------------------------------------------------------

    def _handle_join_room(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()

        # Room must exist in the database.
        if not self._db.room_exists(room_name):
            self._send_err(f"Room '{room_name}' does not exist.")
            return

        # Idempotent join — returns False if already in room.
        newly_joined = self._rooms.join_room(self._username, room_name)

        # Send room history regardless (re-joining still shows history).
        history = self._db.get_room_history(room_name)

        self._send_ok(
            f"Joined room '{room_name}'.",
        )

        # Push history as a separate packet so the client can render it.
        if history:
            send_packet(self._sock, make_history_packet(history))

        # Notify other room members only on a fresh join.
        if newly_joined:
            notif = make_notification_push(
                room_name,
                f"📥 {self._username} joined the room.",
            )
            self._rooms.broadcast_to_room(room_name, notif, exclude=self._username)
            logger.info("'%s' joined room '%s'.", self._username, room_name)

    # ------------------------------------------------------------------
    # Handler: leave_room
    # ------------------------------------------------------------------

    def _handle_leave_room(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()

        if not self._rooms.is_in_room(self._username, room_name):
            self._send_err(f"You are not in room '{room_name}'.")
            return

        self._rooms.leave_room(self._username, room_name)
        self._send_ok(f"Left room '{room_name}'.")

        # Notify remaining members.
        notif = make_notification_push(
            room_name,
            f"📤 {self._username} left the room.",
        )
        self._rooms.broadcast_to_room(room_name, notif)
        logger.info("'%s' left room '%s'.", self._username, room_name)

    # ------------------------------------------------------------------
    # Handler: broadcast
    # ------------------------------------------------------------------

    def _handle_broadcast(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()
        message   = packet["message"].strip()

        if not message:
            self._send_err("Message cannot be empty.")
            return

        if not self._rooms.is_in_room(self._username, room_name):
            self._send_err(
                f"You are not in room '{room_name}'. Join the room first."
            )
            return

        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Persist before broadcasting (so history is consistent).
        self._db.save_message(room_name, self._username, message, timestamp)

        push = make_broadcast_push(room_name, self._username, message, timestamp)

        # Send to everyone in the room INCLUDING the sender
        # so their terminal shows the message in the shared flow.
        self._rooms.broadcast_to_room(room_name, push)

        logger.info(
            "Broadcast in '%s' by '%s': %s",
            room_name, self._username, message[:60],
        )

    # ------------------------------------------------------------------
    # Handler: private_message
    # ------------------------------------------------------------------

    def _handle_private_message(self, packet: dict) -> None:
        if not self._require_login():
            return

        target  = packet["target"].strip()
        message = packet["message"].strip()

        if not message:
            self._send_err("Message cannot be empty.")
            return

        if target == self._username:
            self._send_err("You cannot send a private message to yourself.")
            return

        if not self._rooms.is_online(target):
            self._send_err(f"User '{target}' is not online.")
            return

        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        push = make_private_push(self._username, message, timestamp)
        delivered = self._rooms.send_to_user(target, push)

        if delivered:
            # Confirm to sender.
            self._send_ok(f"Private message sent to '{target}'.")
            logger.info(
                "Private message: '%s' → '%s': %s",
                self._username, target, message[:60],
            )
        else:
            self._send_err(f"Failed to deliver message to '{target}'.")

    # ------------------------------------------------------------------
    # Handler: get_rooms
    # ------------------------------------------------------------------

    def _handle_get_rooms(self, packet: dict) -> None:
        if not self._require_login():
            return

        rooms = self._db.get_all_rooms()
        send_packet(self._sock, make_room_list_packet(rooms))

    # ------------------------------------------------------------------
    # Handler: get_users
    # ------------------------------------------------------------------

    def _handle_get_users(self, packet: dict) -> None:
        if not self._require_login():
            return

        users = self._rooms.get_online_users()
        send_packet(self._sock, make_user_list_packet(users))

    # ------------------------------------------------------------------
    # Cleanup — called when the thread is exiting
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        """
        Remove the user from the online list and notify all their rooms.
        Always safe to call — handles the case where login never happened.
        """
        if self._username:
            # Capture rooms before removing the user.
            user_rooms = self._rooms.get_user_rooms(self._username)

            self._rooms.remove_user(self._username)

            # Notify each room the user was in.
            for room_name in user_rooms:
                notif = make_notification_push(
                    room_name,
                    f"⚠️  {self._username} disconnected.",
                )
                self._rooms.broadcast_to_room(room_name, notif)

            logger.info(
                "Cleaned up session for '%s' (was in: %s).",
                self._username,
                user_rooms,
            )
            self._username = None

        try:
            self._sock.close()
        except OSError:
            pass

        logger.debug("Socket closed for %s:%d", *self._addr)


# ─────────────────────────────────────────────────────────────────────────────
# ChatServer — accept loop
# ─────────────────────────────────────────────────────────────────────────────

class ChatServer:
    """
    TCP server that accepts connections and spawns ClientHandler threads.
    """

    def __init__(
        self,
        host: str = HOST,
        port: int = PORT,
        db: Database | None = None,
    ) -> None:
        self._host  = host
        self._port  = port
        self._db    = db or Database()
        self._rooms = RoomManager()
        self._server_sock: socket.socket | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Startup / Shutdown
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Initialise the database, bind the TCP socket, and enter the
        accept loop.  Blocks until the server is stopped.
        """
        self._db.initialise()

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR lets us restart the server immediately after a crash
        # without waiting for the OS TIME_WAIT period to expire.
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(BACKLOG)
        self._running = True

        logger.info(
            "╔══════════════════════════════════════════╗\n"
            "  Multi-Chat Room Server started\n"
            "  Listening on %s:%d\n"
            "  Press Ctrl+C to stop.\n"
            "╚══════════════════════════════════════════╝",
            self._host, self._port,
        )

        self._accept_loop()

    def stop(self) -> None:
        """Gracefully stop the server."""
        logger.info("Server shutting down…")
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        self._db.close()
        logger.info("Server stopped.")

    # ------------------------------------------------------------------
    # Accept loop
    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        """
        Blocking loop: accept new connections and spawn ClientHandler threads.
        """
        while self._running:
            try:
                client_sock, client_addr = self._server_sock.accept()
            except OSError:
                # Server socket was closed by stop() — exit the loop.
                break

            # Optional: set a socket-level timeout on the client side
            # to detect half-open connections (network failure, not clean close).
            client_sock.settimeout(None)   # blocking; recv_packet handles timeouts

            handler = ClientHandler(
                client_sock=client_sock,
                client_addr=client_addr,
                db=self._db,
                rooms=self._rooms,
            )
            t = threading.Thread(
                target=handler.run,
                name=f"ClientHandler-{client_addr[0]}:{client_addr[1]}",
                daemon=True,   # dies automatically when main thread exits
            )
            t.start()
            logger.debug(
                "Spawned thread '%s' (active threads: %d)",
                t.name,
                threading.active_count(),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    import logging as _logging

    # Parse optional --debug flag.
    level = _logging.DEBUG if "--debug" in sys.argv else _logging.INFO
    setup_logger(level=level)

    server = ChatServer(host=HOST, port=PORT)
    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
