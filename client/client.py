"""
client/client.py
----------------
Multi-Chat Room Client — Command Line Interface.

Architecture
------------
  Main Thread:
    • Connects to the server via TCP.
    • Reads user input from stdin in a blocking loop.
    • Parses commands and sends the appropriate JSON packet.

  Receiver Thread (daemon):
    • Runs concurrently with the main thread.
    • Calls recv_packet() in a loop — blocks until a packet arrives.
    • Prints all server responses and push messages to the terminal.
    • Sets a threading.Event(_stop_event) when the server closes the
      connection so the main thread can exit cleanly.

"Current room" context:
    The client tracks one active room (_current_room).  Once you join
    a room, plain text input (not starting with '/') is sent as a
    broadcast to that room.  Use /join <room> to switch rooms.

Commands
--------
    /register <username> <password>  — Create a new account
    /login    <username> <password>  — Log in
    /logout                          — Log out and keep the client open
    /create   <room>                 — Create a new chat room
    /join     <room>                 — Join a room (sets current room)
    /leave    [room]                 — Leave a room (defaults to current)
    /rooms                           — List all rooms
    /users                           — List online users
    /pm       <username> <message>   — Send a private message
    /room     <room>                 — Switch active room without re-joining
    /help                            — Show this help text
    /quit  or  /exit                 — Disconnect and exit

Typing any text NOT starting with '/' sends it as a broadcast
to the currently active room.
"""

import socket
import threading
import sys
import os
import logging

# ── Ensure the project root is on sys.path so `client.protocol` resolves ─────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.protocol import (
    send_packet,
    recv_packet,
    build_register,
    build_login,
    build_logout,
    build_create_room,
    build_join_room,
    build_leave_room,
    build_broadcast,
    build_private_message,
    build_get_rooms,
    build_get_users,
)

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_HOST = os.environ.get("CHAT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("CHAT_PORT", "9090"))

logging.basicConfig(level=logging.WARNING)   # suppress debug noise on the client

# ── ANSI colour helpers ───────────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI colour code (no-op if not a TTY)."""
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text

def _cyan(t):    return _c("36",    t)
def _green(t):   return _c("32",    t)
def _yellow(t):  return _c("33",    t)
def _red(t):     return _c("31",    t)
def _magenta(t): return _c("35",    t)
def _bold(t):    return _c("1",     t)
def _grey(t):    return _c("38;5;240", t)
def _blue(t):    return _c("34",    t)


# ─────────────────────────────────────────────────────────────────────────────
# ChatClient
# ─────────────────────────────────────────────────────────────────────────────

class ChatClient:
    """
    Manages the connection to the server and the CLI interaction loop.
    """

    HELP_TEXT = """
╔══════════════════════════════════════════════════════════════╗
║              Multi-Chat Room — Command Reference             ║
╠══════════════════════════════════════════════════════════════╣
║  /register <user> <pass>   Create a new account              ║
║  /login    <user> <pass>   Log in to your account            ║
║  /logout                   Log out (keeps client open)       ║
╠══════════════════════════════════════════════════════════════╣
║  /create <room>            Create a new chat room            ║
║  /join   <room>            Join a room (sets active room)    ║
║  /leave  [room]            Leave a room (default: active)    ║
║  /room   <room>            Switch active room context        ║
╠══════════════════════════════════════════════════════════════╣
║  /rooms                    List all available rooms          ║
║  /users                    List online users                 ║
║  /pm <user> <message>      Send a private message            ║
╠══════════════════════════════════════════════════════════════╣
║  <text>                    Broadcast to active room          ║
║  /help                     Show this help text               ║
║  /quit  or  /exit          Disconnect and exit               ║
╚══════════════════════════════════════════════════════════════╝
"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._host         = host
        self._port         = port
        self._sock: socket.socket | None = None
        self._connected    = False
        self._stop_event   = threading.Event()
        self._current_room: str | None = None   # active room for plain-text sends
        self._username: str | None = None        # set on successful login (client-side)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Establish a TCP connection to the server.
        Returns True on success, False on failure.
        """
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.connect((self._host, self._port))
            self._connected = True
            return True
        except ConnectionRefusedError:
            print(_red(f"✗ Connection refused — is the server running on {self._host}:{self._port}?"))
            return False
        except OSError as exc:
            print(_red(f"✗ Connection error: {exc}"))
            return False

    def disconnect(self) -> None:
        """Close the socket cleanly."""
        self._connected = False
        self._stop_event.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Receiver thread
    # ------------------------------------------------------------------

    def _receiver_loop(self) -> None:
        """
        Daemon thread: reads packets from the server and renders them.
        Exits when the connection drops or _stop_event is set.
        """
        while not self._stop_event.is_set():
            packet = recv_packet(self._sock)

            if packet is None:
                # Server closed the connection.
                if not self._stop_event.is_set():
                    print(_red("\n⚠  Server disconnected. Press Enter to exit."))
                self._stop_event.set()
                break

            if not packet:
                continue   # empty / malformed — skip silently

            self._render_packet(packet)

    def _render_packet(self, packet: dict) -> None:
        """
        Format and print a single server packet.
        All output from this thread is prefixed with a newline so it
        does not collide mid-line with the input prompt.
        """
        ptype  = packet.get("type")
        status = packet.get("status")

        # ── Standard request/response ─────────────────────────────────
        if status == "ok":
            msg = packet.get("message", "OK")
            print(f"\n{_green('✓')} {msg}")
            return

        if status == "error":
            msg = packet.get("message", "Unknown error.")
            print(f"\n{_red('✗')} {msg}")
            return

        # ── Room broadcast push ───────────────────────────────────────
        if ptype == "broadcast":
            room      = packet.get("room", "?")
            sender    = packet.get("sender", "?")
            message   = packet.get("message", "")
            timestamp = packet.get("timestamp", "")
            ts_str    = _grey(f"[{timestamp}]") if timestamp else ""
            room_tag  = _cyan(f"[{room}]")
            name_tag  = _bold(_yellow(sender))
            print(f"\n{ts_str} {room_tag} {name_tag}: {message}")
            return

        # ── Private message push ──────────────────────────────────────
        if ptype == "private_message":
            sender    = packet.get("sender", "?")
            message   = packet.get("message", "")
            timestamp = packet.get("timestamp", "")
            ts_str    = _grey(f"[{timestamp}]") if timestamp else ""
            print(f"\n{ts_str} {_magenta('📩 [PM]')} {_bold(sender)}: {message}")
            return

        # ── Notification push (join / leave / disconnect) ─────────────
        if ptype == "notification":
            room    = packet.get("room", "?")
            message = packet.get("message", "")
            print(f"\n{_grey(f'── [{room}] {message} ──')}")
            return

        # ── Room history (on join) ────────────────────────────────────
        if ptype == "history":
            messages = packet.get("messages", [])
            if not messages:
                print(_grey("\n  (No message history for this room.)"))
                return
            print(_grey(f"\n  ── History ({'─' * 40})"))
            for m in messages:
                ts      = _grey(f"[{m.get('timestamp', '')}]")
                sender  = _bold(_yellow(m.get("sender", "?")))
                content = m.get("message", "")
                print(f"  {ts} {sender}: {content}")
            print(_grey(f"  {'─' * 49}"))
            return

        # ── Room list ─────────────────────────────────────────────────
        if ptype == "room_list":
            rooms = packet.get("rooms", [])
            if not rooms:
                print(_yellow("\n  No rooms exist yet. Create one with /create <room>."))
                return
            print(_blue(f"\n  ── Available Rooms ({len(rooms)}) {'─' * 30}"))
            for r in rooms:
                name    = _cyan(r.get("room_name", "?"))
                creator = _grey(f"(created by {r.get('created_by', '?')})")
                print(f"    • {name}  {creator}")
            print(_blue(f"  {'─' * 50}"))
            return

        # ── User list ─────────────────────────────────────────────────
        if ptype == "user_list":
            users = packet.get("users", [])
            if not users:
                print(_yellow("\n  No users currently online."))
                return
            print(_blue(f"\n  ── Online Users ({len(users)}) {'─' * 33}"))
            for u in users:
                print(f"    • {_green(u)}")
            print(_blue(f"  {'─' * 50}"))
            return

        # ── Unknown packet type ───────────────────────────────────────
        print(_grey(f"\n  [server] {packet}"))

    # ------------------------------------------------------------------
    # Command parser
    # ------------------------------------------------------------------

    def _parse_and_send(self, line: str) -> bool:
        """
        Parse a user input line and send the corresponding packet.

        Returns False when the client should exit, True to continue.
        """
        line = line.strip()
        if not line:
            return True

        # ── Slash commands ────────────────────────────────────────────
        if line.startswith("/"):
            parts = line.split(maxsplit=2)
            cmd   = parts[0].lower()

            # /help
            if cmd == "/help":
                print(self.HELP_TEXT)
                return True

            # /quit / /exit
            if cmd in ("/quit", "/exit"):
                if self._connected:
                    send_packet(self._sock, build_logout())
                return False

            # /register <user> <pass>
            if cmd == "/register":
                if len(parts) < 3:
                    print(_red("Usage: /register <username> <password>"))
                    return True
                send_packet(self._sock, build_register(parts[1], parts[2]))
                return True

            # /login <user> <pass>
            if cmd == "/login":
                if len(parts) < 3:
                    print(_red("Usage: /login <username> <password>"))
                    return True
                self._username = parts[1]   # optimistically set; cleared on error
                send_packet(self._sock, build_login(parts[1], parts[2]))
                return True

            # /logout
            if cmd == "/logout":
                send_packet(self._sock, build_logout())
                self._username     = None
                self._current_room = None
                return True

            # /create <room>
            if cmd == "/create":
                if len(parts) < 2:
                    print(_red("Usage: /create <room_name>"))
                    return True
                send_packet(self._sock, build_create_room(parts[1]))
                return True

            # /join <room>
            if cmd == "/join":
                if len(parts) < 2:
                    print(_red("Usage: /join <room_name>"))
                    return True
                room = parts[1]
                self._current_room = room
                print(_grey(f"  → Active room set to '{room}'."))
                send_packet(self._sock, build_join_room(room))
                return True

            # /leave [room]
            if cmd == "/leave":
                if len(parts) >= 2:
                    room = parts[1]
                elif self._current_room:
                    room = self._current_room
                else:
                    print(_red("Usage: /leave <room_name>  (or join a room first)"))
                    return True
                if room == self._current_room:
                    self._current_room = None
                    print(_grey("  → Active room cleared."))
                send_packet(self._sock, build_leave_room(room))
                return True

            # /room <room>  — switch active room context (no re-join)
            if cmd == "/room":
                if len(parts) < 2:
                    print(_red("Usage: /room <room_name>"))
                    return True
                self._current_room = parts[1]
                print(_grey(f"  → Active room switched to '{parts[1]}'."))
                return True

            # /rooms
            if cmd == "/rooms":
                send_packet(self._sock, build_get_rooms())
                return True

            # /users
            if cmd == "/users":
                send_packet(self._sock, build_get_users())
                return True

            # /pm <target> <message>
            if cmd == "/pm":
                # parts[0]=/pm  parts[1]=target  parts[2]=message
                raw = line.split(maxsplit=2)
                if len(raw) < 3:
                    print(_red("Usage: /pm <username> <message>"))
                    return True
                target  = raw[1]
                message = raw[2]
                send_packet(self._sock, build_private_message(target, message))
                return True

            # Unknown command
            print(_red(f"Unknown command: '{cmd}'. Type /help for commands."))
            return True

        # ── Plain text → broadcast to current room ────────────────────
        if self._current_room is None:
            print(_yellow(
                "  No active room. Use /join <room> to join one first,\n"
                "  or /rooms to see available rooms."
            ))
            return True

        send_packet(self._sock, build_broadcast(self._current_room, line))
        return True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Connect to the server, start the receiver thread, and enter
        the interactive input loop.
        """
        print(_bold(_cyan("""
  ╔═══════════════════════════════════════════╗
  ║       Multi-Chat Room Client v1.0         ║
  ╚═══════════════════════════════════════════╝""")))
        print(f"  Connecting to {_cyan(self._host)}:{_cyan(str(self._port))} …")

        if not self.connect():
            return

        print(_green("  ✓ Connected! Type /help for available commands.\n"))

        # Start the receiver daemon thread.
        receiver = threading.Thread(
            target=self._receiver_loop,
            name="ReceiverThread",
            daemon=True,
        )
        receiver.start()

        # ── Input loop ────────────────────────────────────────────────
        try:
            while not self._stop_event.is_set():
                # Build prompt showing current context.
                if self._username and self._current_room:
                    prompt = f"{_green(self._username)}@{_cyan(self._current_room)} > "
                elif self._username:
                    prompt = f"{_green(self._username)} > "
                else:
                    prompt = "guest > "

                try:
                    line = input(prompt)
                except EOFError:
                    # Ctrl+D
                    break
                except KeyboardInterrupt:
                    print()
                    break

                if self._stop_event.is_set():
                    break

                should_continue = self._parse_and_send(line)
                if not should_continue:
                    break

        finally:
            self.disconnect()
            print(_yellow("\n  Goodbye! 👋"))


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Parse optional --host and --port CLI arguments, then start the client.

    Usage:
        python -m client.client
        python -m client.client --host 192.168.1.5 --port 9090
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Multi-Chat Room Client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server hostname or IP")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Server port")
    args = parser.parse_args()

    client = ChatClient(host=args.host, port=args.port)
    client.run()


if __name__ == "__main__":
    main()
