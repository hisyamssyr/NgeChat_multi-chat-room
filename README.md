[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/4SHtB1vz)

# 💬 Multi-Chat Room Application

> **Final Project — Computer Network Programming**
> TCP-based multi-room chat application using Python standard libraries only.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Protocol](#protocol)
- [Getting Started](#getting-started)
- [Command Reference](#command-reference)
- [Testing with 3 Clients](#testing-with-3-clients)

---

## Overview

A real-time multi-room chat application built with:

- **TCP Socket Server** — multi-threaded, one thread per client
- **GUI Client** — modern PyQt6 desktop app with dark theme (3-panel layout)
- **CLI Client** — terminal-based fallback client, fully preserved
- **SQLite** — persists users, rooms, and message history
- **JSON Protocol** — length-prefixed framing over raw TCP

Supported features: user registration & login, room create/join/leave, broadcast messaging, private messages (DM), online user list, room history on join, and a modern desktop GUI.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| Transport | `socket` (TCP) |
| Concurrency | `threading` |
| Database | `sqlite3` |
| Serialisation | `json` |
| Auth | `hashlib` (SHA-256) |
| Logging | `logging` + `logging.handlers` |
| GUI | **PyQt6** |

> ✅ Server and CLI client use **100% Python standard library** — no extra dependencies.
> ✅ GUI client requires `PyQt6` — install with `pip install -r requirements.txt`.

---

## Architecture

```
┌─────────────────────┐                  ┌────────────────────────────────────┐
│   GUI Client        │   TCP / JSON     │         TCP Server                 │
│  (gui_main.py)      │ ◄──────────────  │  ┌──────────────────────────────┐  │
│  ┌───────────────┐  │                  │  │  Main Thread (accept loop)   │  │
│  │ MainWindow    │  │ ──────────────►  │  └──────────┬───────────────────┘  │
│  │ (Qt GUI)      │  │                  │             │ spawn per client       │
│  └──────┬────────┘  │                  │  ┌──────────▼───────────────────┐  │
│         │ signals   │                  │  │  ClientHandler Thread (×N)   │  │
│  ┌──────▼────────┐  │                  │  │  • recv / parse packet       │  │
│  │ NetworkClient │  │                  │  │  • dispatch to handler       │  │
│  │ (QObject)     │  │                  │  │  • send response / push      │  │
│  └──────┬────────┘  │                  │  └──────────┬───────────────────┘  │
│         │ daemon    │                  │             │                        │
│  ┌──────▼────────┐  │                  │  ┌──────────▼───────────────────┐  │
│  │ ReceiverThread│  │                  │  │  Shared State (thread-safe)  │  │
│  └───────────────┘  │                  │  │  RoomManager  (RLock)        │  │
└─────────────────────┘                  │  │  Database     (Lock + WAL)   │  │
                                         │  └──────────────────────────────┘  │
┌─────────────────────┐                  └────────────────────────────────────┘
│   CLI Client        │   TCP / JSON
│  (client.py)        │ ◄──────────────  (same server, same protocol)
└─────────────────────┘
```

### GUI Signal Flow

The GUI uses Qt's signal/slot mechanism for thread-safe UI updates:

```
ReceiverThread (daemon)          Qt GUI Thread (main)
────────────────────────         ─────────────────────────────────────
recv_packet()                    NetworkClient.packet_received(dict)
  → emit packet_received  ──►      → MainWindow.on_packet()
                                        ├─ broadcast   → append to chat area
                                        ├─ private_msg → show PM (purple)
                                        ├─ notification→ system message
                                        ├─ history     → prepend on room join
                                        ├─ room_list   → populate left panel
                                        └─ user_list   → populate right panel
```

### Threading Model

| Thread | Count | Responsibility |
|---|---|---|
| Main / Accept | 1 | `server.accept()` loop; spawns a `ClientHandler` per connection |
| ClientHandler | 1 per client | Owns client socket; runs recv loop; dispatches packets |
| CLI Receiver | 1 (CLI client) | Daemon thread; prints server pushes while main thread reads input |
| GUI Receiver | 1 (GUI client) | Daemon thread; emits `packet_received` Qt signal to GUI thread |

---

## Project Structure

```
project/
│
├── server/
│   ├── server.py           # TCP accept loop + ClientHandler dispatch
│   ├── database.py         # SQLite CRUD (users, rooms, messages)
│   ├── room_manager.py     # In-memory online users & room membership
│   ├── protocol.py         # Framing, packet builders, validation
│   └── logger.py           # Colourised console + rotating file logger
│
├── client/
│   ├── client.py           # CLI client — loop + receiver daemon thread
│   ├── protocol.py         # Wire framing + packet builder functions
│   ├── network_client.py   # Qt-aware networking bridge (QObject + signals)
│   ├── gui_main.py         # ★ GUI entry point  →  python -m client.gui_main
│   └── gui/
│       ├── styles.py       # Dark theme QSS stylesheet + colour constants
│       ├── dialogs.py      # CreateRoomDialog, PrivateMsgDialog
│       ├── login_window.py # Login / Register form (QDialog)
│       └── main_window.py  # 3-panel main window (QMainWindow)
│
├── database/
│   └── chat.db             # SQLite database (auto-created on first run)
│
├── logs/
│   └── server.log          # Rotating server log (auto-created)
│
└── requirements.txt        # PyQt6 (only external dependency)
```

---

## Database Schema

```sql
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL          -- SHA-256 hex digest
);

CREATE TABLE rooms (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_name  TEXT UNIQUE NOT NULL,
    created_by TEXT NOT NULL
);

CREATE TABLE messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    room_name TEXT NOT NULL,
    sender    TEXT NOT NULL,
    message   TEXT NOT NULL,
    timestamp TEXT NOT NULL              -- ISO-8601 UTC string
);
```

---

## Protocol

All packets use **4-byte length-prefix + UTF-8 JSON**:

```
┌─────────────────────┬──────────────────────────────────┐
│  4 bytes (uint32)   │  N bytes (UTF-8 JSON payload)    │
│  big-endian length  │  { "type": "...", ... }           │
└─────────────────────┴──────────────────────────────────┘
```

### Client → Server Packets

| Type | Required Fields |
|---|---|
| `register` | `username`, `password` |
| `login` | `username`, `password` |
| `logout` | — |
| `create_room` | `room` |
| `join_room` | `room` |
| `leave_room` | `room` |
| `broadcast` | `room`, `message` |
| `private_message` | `target`, `message` |
| `get_rooms` | — |
| `get_users` | — |

### Server → Client Responses

```jsonc
// Request response
{ "status": "ok",    "message": "Login successful." }
{ "status": "error", "message": "Incorrect password." }

// Push: room broadcast
{ "type": "broadcast", "room": "AI", "sender": "alice", "message": "Hello", "timestamp": "..." }

// Push: private message
{ "type": "private_message", "sender": "bob", "message": "Hey", "timestamp": "..." }

// Push: join / leave notification
{ "type": "notification", "room": "AI", "message": "charlie joined the room" }

// Room history on join
{ "type": "history", "messages": [ { "sender": "...", "message": "...", "timestamp": "..." } ] }
```

---

## Getting Started

### Prerequisites

- Python **3.13+**
- PyQt6 (for the GUI client only):
  ```bash
  pip install -r requirements.txt
  ```
- Three terminal windows (or tabs)

### 1 — Start the Server

Open **Terminal 1** and run:

```bash
cd path/to/g04-final-project-d-ngechatt
python -m server.server
```

Expected output:

```
2026-06-08 04:15:00  INFO      server.logger   Logger initialised — level=INFO
2026-06-08 04:15:00  INFO      server.server   Multi-Chat Room Server started
                                               Listening on 0.0.0.0:9090
                                               Press Ctrl+C to stop.
```

> **Optional:** pass `--debug` for verbose packet-level logging:
> ```bash
> python -m server.server --debug
> ```

### 2a — Launch the GUI Client ⭐ (Recommended)

Open a new terminal and run:

```bash
python -m client.gui_main
```

Connect to a remote server:

```bash
python -m client.gui_main --host 192.168.1.5 --port 9090
```

The **Login window** opens. Fill in your credentials and server address, then click **Login** or **Register New Account**.

After authentication the **main window** appears:

```
┌──────────────────────────────────────────────────────────────────┐
│  🗨 Multi-Chat Room                 [alice]  [↺ Refresh] [Logout]│
├──────────────┬───────────────────────────────┬───────────────────┤
│ ROOMS        │ # AI                          │ ONLINE            │
│ ──────────── │ ─────────────────────────── │ ────────────────── │
│ 🟢 AI        │ [14:01] bob: Hello!           │ 🟢 alice          │
│ 💬 Gaming    │ [14:02] alice: Hey there!     │ 🟢 bob            │
│ 💬 Network   │ ── charlie joined the room ── │ 🟢 charlie        │
│              │                               │                   │
│ [＋ New Room]│                               │ [✉ Send PM]       │
├──────────────┴───────────────────────────────┴───────────────────┤
│ [📎] [🎤]   Type a message…  (Enter to send)      [  Send  ▶  ] │
└──────────────────────────────────────────────────────────────────┘
```

### 2b — Launch the CLI Client (Alternative)

```bash
python -m client.client
```

Connect to a remote server:

```bash
python -m client.client --host 192.168.1.5 --port 9090
```

> 💡 Both clients connect to the **same server** using the **same JSON/TCP protocol**. You can mix GUI and CLI clients in the same session.

### 3 — Stop the Server

Press `Ctrl+C` in Terminal 1. The server performs a graceful shutdown (closes the database connection cleanly).

---

## Command Reference

Once connected, type these commands in the client terminal:

| Command | Description |
|---|---|
| `/register <user> <pass>` | Create a new account |
| `/login <user> <pass>` | Log in |
| `/logout` | Log out (keeps client open) |
| `/create <room>` | Create a new chat room |
| `/join <room>` | Join a room *(sets active room)* |
| `/leave [room]` | Leave a room *(defaults to active room)* |
| `/room <room>` | Switch active room without re-joining |
| `/rooms` | List all available rooms |
| `/users` | List currently online users |
| `/pm <user> <message>` | Send a private message to a user |
| `<any text>` | Broadcast to the currently active room |
| `/help` | Show command reference |
| `/quit` or `/exit` | Disconnect and close the client |

> 💡 **Tip:** After `/join <room>`, just type and press Enter to chat — no `/broadcast` prefix needed.

---

## Testing with 3 Clients

Follow this step-by-step scenario to verify all features work correctly.

> 💡 You can use **GUI clients**, **CLI clients**, or **a mix of both** — the protocol is identical.

### Setup

Start the server in Terminal 1, then open Terminals 2, 3, and 4.

- **GUI:** `python -m client.gui_main`
- **CLI:** `python -m client.client`

---

### Step 1 — Register & Login

**Terminal 2 (Alice):**
```
/register alice pass123
/login alice pass123
```

**Terminal 3 (Bob):**
```
/register bob pass456
/login bob pass456
```

**Terminal 4 (Charlie):**
```
/register charlie pass789
/login charlie pass789
```

✅ Each terminal should receive: `✓ Login successful.`

---

### Step 2 — Create & Join Rooms

**Alice** creates two rooms:
```
/create AI
/create General
```

**Alice** joins `AI`:
```
/join AI
```

**Bob** joins `AI`:
```
/join AI
```
> ✅ Alice's terminal should show: `── [AI] 📥 bob joined the room. ──`

**Charlie** joins `General`:
```
/join General
```

---

### Step 3 — Broadcast Messaging

**Alice** (active room: `AI`) types:
```
Hello everyone in AI!
```
> ✅ Both Alice's and Bob's terminals show the message.
> ✅ Charlie does NOT see it (he's in a different room).

**Bob** replies:
```
Hey Alice, what's up?
```
> ✅ Both Alice and Bob see Bob's message.

---

### Step 4 — Private Message

**Alice** sends a private message to Charlie:
```
/pm charlie Hey Charlie, you're in General right?
```
> ✅ Charlie's terminal shows: `📩 [PM] alice: Hey Charlie, you're in General right?`
> ✅ Bob does NOT see this message.

---

### Step 5 — List Rooms & Users

Any client can run:
```
/rooms
/users
```
> ✅ `/rooms` lists: `AI` and `General`
> ✅ `/users` lists: `alice`, `bob`, `charlie`

---

### Step 6 — Join Multiple Rooms & Room History

**Charlie** joins `AI`:
```
/join AI
```
> ✅ Charlie sees the **history** of previous messages in `AI`.
> ✅ Alice and Bob see: `── [AI] 📥 charlie joined the room. ──`

**Charlie** switches active room to `AI`:
```
/room AI
Hello from Charlie!
```
> ✅ All three users in `AI` see the message.

---

### Step 7 — Leave Room & Disconnect

**Bob** leaves `AI`:
```
/leave AI
```
> ✅ Alice and Charlie see: `── [AI] 📤 bob left the room. ──`

**Charlie** closes their terminal (Ctrl+C):
> ✅ Alice sees: `── [AI] ⚠️  charlie disconnected. ──`

---

### Expected Final State

| User | Status | Room |
|---|---|---|
| Alice | Online | AI |
| Bob | Online | *(no active room)* |
| Charlie | Offline | — |

---

## Logs

Server logs are written to `logs/server.log` and rotated at 5 MB (3 backups kept).

```bash
# View live logs
Get-Content logs\server.log -Wait     # PowerShell
tail -f logs/server.log               # bash / WSL
```
