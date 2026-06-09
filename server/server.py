import socket
import threading
import ssl
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.logger       import setup_logger
from server.database     import Database
from server.room_manager import RoomManager
from server.protocol     import (
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
    make_friend_list_packet,
    make_friend_request_push,
)

HOST     = os.environ.get("CHAT_HOST", "0.0.0.0")
PORT     = int(os.environ.get("CHAT_PORT", "9090"))
BACKLOG  = 10   # max queued connections before accept()

logger = logging.getLogger(__name__)


class ClientHandler:
    """Manages the full lifecycle of one TCP client connection.

    Runs in its own daemon thread; communicates with the main thread
    only through thread-safe Database and RoomManager methods.
    """

    def __init__(
        self,
        client_sock: socket.socket,
        client_addr: tuple,
        db: Database,
        rooms: RoomManager,
    ) -> None:
        self._sock     = client_sock
        self._addr     = client_addr
        self._db       = db
        self._rooms    = rooms
        self._username: str | None = None  # set on successful login
        self._running  = True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info("New connection from %s:%d", *self._addr)
        try:
            while self._running:
                packet = recv_packet(self._sock)

                if packet is None:
                    logger.info("Client %s:%d disconnected.", *self._addr)
                    break

                if not packet:
                    send_packet(self._sock, make_response("error", "Empty or malformed packet."))
                    continue

                self._handle_packet(packet)

        except Exception as exc:
            logger.error(
                "Unhandled exception for %s:%d — %s", *self._addr, exc, exc_info=True
            )
        finally:
            self._cleanup()

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _handle_packet(self, packet: dict) -> None:
        try:
            ptype = validate_packet(packet)
        except PacketError as exc:
            send_packet(self._sock, make_response("error", str(exc)))
            logger.warning("PacketError from %s:%d — %s", *self._addr, exc)
            return

        dispatch = {
            "register":        self._handle_register,
            "login":           self._handle_login,
            "logout":          self._handle_logout,
            "create_room":     self._handle_create_room,
            "join_room":       self._handle_join_room,
            "join_by_code":    self._handle_join_by_code,
            "leave_room":      self._handle_leave_room,
            "broadcast":       self._handle_broadcast,
            "private_message": self._handle_private_message,
            "get_rooms":       self._handle_get_rooms,
            "get_users":       self._handle_get_users,
            "delete_room":     self._handle_delete_room,
            "add_friend":      self._handle_add_friend,
            "remove_friend":   self._handle_remove_friend,
            "get_friends":     self._handle_get_friends,
            "accept_friend":   self._handle_accept_friend,
            "decline_friend":  self._handle_decline_friend,
            "get_pending_requests": self._handle_get_pending_requests,
        }
        handler = dispatch.get(ptype)
        if handler:
            handler(packet)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _require_login(self) -> bool:
        if self._username is None:
            send_packet(self._sock, make_response("error", "You must be logged in to do that."))
            return False
        return True

    def _send_ok(self, message: str, **extra) -> None:
        send_packet(self._sock, make_response("ok", message, **extra))

    def _send_err(self, message: str) -> None:
        send_packet(self._sock, make_response("error", message))

    # ------------------------------------------------------------------
    # Handlers
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

    def _handle_login(self, packet: dict) -> None:
        username = packet["username"].strip()
        password = packet["password"]

        if self._username is not None:
            self._send_err(f"Already logged in as '{self._username}'.")
            return

        if self._rooms.is_online(username):
            self._send_err(f"'{username}' is already logged in from another session.")
            return

        ok, msg = self._db.validate_login(username, password)
        if not ok:
            self._send_err(msg)
            return

        self._username = username
        self._rooms.add_user(username, self._sock)
        self._send_ok(msg)
        logger.info("User logged in: %s from %s:%d", username, *self._addr)

        # Notify all online friends that this user is now online.
        self._push_friend_status_to_friends(username)

    def _handle_logout(self, packet: dict) -> None:
        if not self._require_login():
            return
        username = self._username
        self._running = False  # exits the recv loop after this handler returns
        self._send_ok("Logged out successfully.")
        logger.info("User logged out: %s", username)
        # _cleanup() runs in the finally block of run()

    def _handle_create_room(self, packet: dict) -> None:
        if not self._require_login():
            return
        room_name = packet["room"].strip()
        ok, msg, invite_code = self._db.create_room(room_name, self._username)
        if ok:
            # Include room_code so the client can display it to the creator.
            send_packet(self._sock, {
                "status":    "ok",
                "message":   msg,
                "room_code": invite_code,
                "room_name": room_name,
            })
        else:
            self._send_err(msg)

    def _handle_join_room(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()
        code      = packet.get("code", "")

        if not self._db.room_exists(room_name):
            self._send_err(f"Room '{room_name}' does not exist.")
            return

        if not self._db.is_room_member(room_name, self._username):
            if not self._db.check_room_code(room_name, code):
                self._send_err("Wrong invite code.")
                return
            self._db.add_room_member(room_name, self._username)
            logger.info("'%s' joined room '%s' with invite code.", self._username, room_name)

        newly_joined = self._rooms.join_room(self._username, room_name)
        history      = self._db.get_room_history(room_name)
        self._send_ok(f"Joined room '{room_name}'.")

        if history:
            send_packet(self._sock, make_history_packet(history))

        if newly_joined:
            notif = make_notification_push(room_name, f"📥 {self._username} joined the room.")
            self._rooms.broadcast_to_room(room_name, notif, exclude=self._username)
            logger.info("'%s' joined room '%s'.", self._username, room_name)

    def _handle_join_by_code(self, packet: dict) -> None:
        if not self._require_login():
            return

        code = packet.get("code", "").strip().upper()
        if not code:
            self._send_err("Invite code is required.")
            return

        room_name = self._db.get_room_by_code(code)
        if not room_name:
            self._send_err("Invalid invite code.")
            return

        if not self._db.is_room_member(room_name, self._username):
            self._db.add_room_member(room_name, self._username)
            logger.info("'%s' joined room '%s' via invite code.", self._username, room_name)

        newly_joined = self._rooms.join_room(self._username, room_name)
        history      = self._db.get_room_history(room_name)

        # Include room_name so the client can switch to the correct view.
        send_packet(self._sock, {
            "status":    "ok",
            "message":   f"Joined room '{room_name}'.",
            "room_name": room_name,
        })

        if history:
            send_packet(self._sock, make_history_packet(history))

        if newly_joined:
            notif = make_notification_push(room_name, f"📥 {self._username} joined the room.")
            self._rooms.broadcast_to_room(room_name, notif, exclude=self._username)

    def _handle_leave_room(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()
        if not self._rooms.is_in_room(self._username, room_name):
            self._send_err(f"You are not in room '{room_name}'.")
            return

        self._rooms.leave_room(self._username, room_name)
        self._db.remove_room_member(room_name, self._username)
        self._send_ok(f"Left room '{room_name}'.")

        notif = make_notification_push(room_name, f"📤 {self._username} left the room.")
        self._rooms.broadcast_to_room(room_name, notif)
        logger.info("'%s' left room '%s' permanently.", self._username, room_name)

    def _handle_delete_room(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()
        ok, msg   = self._db.delete_room(room_name, self._username)
        if not ok:
            self._send_err(msg)
            return

        notif = make_notification_push(
            room_name,
            f"❌ The room '{room_name}' has been permanently deleted by the owner.",
        )
        self._rooms.broadcast_to_room(room_name, notif)
        self._rooms.delete_room(room_name)
        self._send_ok(msg)

    def _handle_broadcast(self, packet: dict) -> None:
        if not self._require_login():
            return

        room_name = packet["room"].strip()
        message   = packet["message"].strip()

        if not message:
            self._send_err("Message cannot be empty.")
            return

        if not self._rooms.is_in_room(self._username, room_name):
            self._send_err(f"You are not in room '{room_name}'. Join the room first.")
            return

        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Persist before broadcasting so history is always consistent.
        self._db.save_message(room_name, self._username, message, timestamp)

        push = make_broadcast_push(room_name, self._username, message, timestamp)
        self._rooms.broadcast_to_room(room_name, push)  # sender included

        logger.info("Broadcast in '%s' by '%s': %s", room_name, self._username, message[:60])

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
        if not self._db.is_friend(self._username, target):
            self._send_err(f"'{target}' is not in your friends list. Add them as a friend first.")
            return
        if not self._rooms.is_online(target):
            self._send_err(f"'{target}' is currently offline.")
            return

        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        push      = make_private_push(self._username, message, timestamp)
        delivered = self._rooms.send_to_user(target, push)

        if delivered:
            self._send_ok(f"Private message sent to '{target}'.")
            logger.info("PM: '%s' → '%s': %s", self._username, target, message[:60])
        else:
            self._send_err(f"Failed to deliver message to '{target}'.")

    def _handle_get_rooms(self, packet: dict) -> None:
        if not self._require_login():
            return
        rooms = self._db.get_all_rooms(self._username)
        send_packet(self._sock, make_room_list_packet(rooms))

    def _handle_get_users(self, packet: dict) -> None:
        if not self._require_login():
            return
        users = self._rooms.get_online_users()
        send_packet(self._sock, make_user_list_packet(users))

    def _handle_get_friends(self, packet: dict) -> None:
        if not self._require_login():
            return
        self._send_friend_list_to(self._username)

    def _handle_get_pending_requests(self, packet: dict) -> None:
        if not self._require_login():
            return
        requests = self._db.get_pending_received(self._username)
        from .protocol import make_pending_requests_list
        send_packet(self._sock, make_pending_requests_list(requests))

    def _handle_add_friend(self, packet: dict) -> None:
        if not self._require_login():
            return
        target    = packet["target"].strip()
        ok, msg   = self._db.send_friend_request(self._username, target)
        if ok:
            self._send_ok(msg)
            # Push real-time notification to the target if they are online.
            target_sock = self._rooms.get_socket(target)
            if target_sock:
                send_packet(target_sock, make_friend_request_push(self._username))
        else:
            self._send_err(msg)

    def _handle_accept_friend(self, packet: dict) -> None:
        if not self._require_login():
            return
        requester = packet["target"].strip()  # the user who sent the original request
        ok, msg   = self._db.accept_friend_request(self._username, requester)
        if ok:
            self._send_ok(msg)
            self._send_friend_list_to(self._username)
            self._send_friend_list_to(requester)
        else:
            self._send_err(msg)

    def _handle_decline_friend(self, packet: dict) -> None:
        if not self._require_login():
            return
        requester = packet["target"].strip()
        ok, msg   = self._db.decline_friend_request(self._username, requester)
        if ok:
            self._send_ok(msg)
        else:
            self._send_err(msg)

    def _handle_remove_friend(self, packet: dict) -> None:
        if not self._require_login():
            return
        target  = packet["target"].strip()
        ok, msg = self._db.remove_friend(self._username, target)
        if ok:
            self._send_ok(msg)
            self._send_friend_list_to(self._username)
            self._send_friend_list_to(target)
        else:
            self._send_err(msg)

    # ------------------------------------------------------------------
    # Friend list push helpers
    # ------------------------------------------------------------------

    def _send_friend_list_to(self, username: str) -> None:
        friends = [
            {"username": f, "online": self._rooms.is_online(f)}
            for f in self._db.get_friends(username)
        ]
        sock = self._rooms.get_socket(username)
        if sock:
            send_packet(sock, make_friend_list_packet(friends))

    def _push_friend_status_to_friends(self, username: str) -> None:
        """Refresh friend lists for all online friends of *username*.

        Called on login and disconnect so the friend's list shows the
        correct online/offline dot without a manual refresh.
        """
        for friend in self._db.get_friends(username):
            if self._rooms.is_online(friend):
                self._send_friend_list_to(friend)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        if self._username:
            user_rooms = self._rooms.get_user_rooms(self._username)
            self._rooms.remove_user(self._username)

            # Must happen after remove_user so the user appears offline to friends.
            self._push_friend_status_to_friends(self._username)

            for room_name in user_rooms:
                notif = make_notification_push(
                    room_name, f"⚠️  {self._username} disconnected."
                )
                self._rooms.broadcast_to_room(room_name, notif)

            logger.info(
                "Cleaned up session for '%s' (was in: %s).", self._username, user_rooms
            )
            self._username = None

        try:
            self._sock.close()
        except OSError:
            pass

        logger.debug("Socket closed for %s:%d", *self._addr)


class ChatServer:
    """TCP server — accepts connections and spawns one ClientHandler thread each."""

    def __init__(self, host: str = HOST, port: int = PORT, db: Database | None = None) -> None:
        self._host        = host
        self._port        = port
        self._db          = db or Database()
        self._rooms       = RoomManager()
        self._server_sock: socket.socket | None = None
        self._running     = False
        
        # Load TLS certificates
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cert_path = os.path.join(base_dir, "certs", "cert.pem")
        key_path  = os.path.join(base_dir, "certs", "key.pem")
        
        self._ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self._ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)

    def start(self) -> None:
        self._db.initialise()

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR avoids "address already in use" on a quick restart.
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(BACKLOG)
        self._running = True

        logger.info(
            "\n==========================================\n"
            "  Multi-Chat Room Server started\n"
            "  Listening on %s:%d\n"
            "  Press Ctrl+C to stop.\n"
            "==========================================",
            self._host, self._port,
        )

        self._accept_loop()

    def stop(self) -> None:
        logger.info("Server shutting down…")
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        self._db.close()
        logger.info("Server stopped.")

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client_sock, client_addr = self._server_sock.accept()
            except OSError:
                break  # server socket closed by stop()

            try:
                secure_sock = self._ssl_context.wrap_socket(client_sock, server_side=True)
            except ssl.SSLError as e:
                logger.error("SSL handshake failed for %s:%d — %s", *client_addr, e)
                client_sock.close()
                continue

            handler = ClientHandler(
                client_sock=secure_sock,
                client_addr=client_addr,
                db=self._db,
                rooms=self._rooms,
            )
            t = threading.Thread(
                target=handler.run,
                name=f"ClientHandler-{client_addr[0]}:{client_addr[1]}",
                daemon=True,
            )
            t.start()
            logger.debug("Spawned thread '%s' (active: %d)", t.name, threading.active_count())


def main() -> None:
    import logging as _logging
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
