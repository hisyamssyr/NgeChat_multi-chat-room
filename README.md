# Multi-Chat Room Application

**Final Project — Computer Network Programming**

A TCP-based multi-room chat application utilizing Python standard libraries for core networking, enhanced with TLS encryption for secure communication.

---

## Table of Contents

- [Overview](#overview)
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Protocol Specification](#protocol-specification)
- [Getting Started](#getting-started)
- [Command Reference](#command-reference)
- [Testing Scenario](#testing-scenario)

---

## Overview

A real-time, multi-room chat application featuring:

- **TCP Socket Server**: Multi-threaded architecture, dedicating one thread per client.
- **Security**: TLS encryption implemented via the `ssl` module to secure all data transmissions.
- **GUI Client**: A modern desktop application built with PyQt6, featuring a three-panel layout and a dark theme.
- **CLI Client**: A fully functional terminal-based alternative client.
- **Data Persistence**: SQLite database for persisting user credentials, room information, and chat history.
- **Custom Protocol**: JSON-based message framing with a 4-byte length prefix over raw TCP.

### Key Features
- User registration and authentication
- Room creation, joining, and leaving
- Real-time broadcast messaging within rooms
- Private messaging (Direct Messages) between online users
- Online user presence tracking
- Automatic room history retrieval upon joining

---

## Architecture & Tech Stack

| Component | Technology |
|---|---|
| **Language** | Python 3.13 |
| **Transport** | `socket` (TCP) |
| **Security** | `ssl` (TLS 1.2/1.3) |
| **Concurrency** | `threading` |
| **Database** | `sqlite3` (with WAL mode) |
| **Serialization** | `json` |
| **Authentication** | `hashlib` (SHA-256) |
| **Logging** | `logging` + `logging.handlers` |
| **GUI Framework** | PyQt6 |

*Note: The server and CLI client are built entirely using the Python standard library. The GUI client requires `PyQt6`.*

### System Architecture

```text
+-----------------------+                    +------------------------------------+
|      GUI Client       |   TCP / TLS / JSON |           TCP Server               |
|     (gui_main.py)     | <----------------> |  +------------------------------+  |
|  +-----------------+  |                    |  |  Main Thread (accept loop)   |  |
|  | MainWindow      |  |                    |  +-------------+----------------+  |
|  | (Qt GUI)        |  |                    |                | spawn per client  |
|  +-------+---------+  |                    |  +-------------v----------------+  |
|          | signals    |                    |  |  ClientHandler Thread (xN)   |  |
|  +-------v---------+  |                    |  |  - recv / parse packet       |  |
|  | NetworkClient   |  |                    |  |  - dispatch to handler       |  |
|  | (QObject)       |  |                    |  |  - send response / push      |  |
|  +-------+---------+  |                    |  +-------------+----------------+  |
|          | daemon     |                    |                |                   |
|  +-------v---------+  |                    |  +-------------v----------------+  |
|  | ReceiverThread  |  |                    |  |  Shared State (thread-safe)  |  |
|  +-----------------+  |                    |  |  RoomManager  (RLock)        |  |
+-----------------------+                    |  |  Database     (Lock + WAL)   |  |
                                             |  +------------------------------+  |
+-----------------------+                    +------------------------------------+
|      CLI Client       |   TCP / TLS / JSON
|     (client.py)       | <----------------> (Same server and protocol)
+-----------------------+
```

---

## Project Structure

```text
project/
|
+-- certs/                  # SSL Certificates (cert.pem, key.pem)
+-- server/
|   +-- server.py           # TCP accept loop, SSL wrapping, Client dispatch
|   +-- database.py         # SQLite CRUD operations
|   +-- room_manager.py     # In-memory online user and room state
|   +-- protocol.py         # Wire framing, packet builders, validation
|   +-- logger.py           # Console and rotating file logger configuration
|
+-- client/
|   +-- client.py           # CLI client (main loop + receiver thread)
|   +-- protocol.py         # Wire framing and packet builders
|   +-- network_client.py   # Qt-aware networking bridge (SSL + QObject)
|   +-- gui_main.py         # GUI entry point
|   +-- gui/
|       +-- styles.py       # QSS stylesheets
|       +-- dialogs.py      # Dialog windows
|       +-- login_window.py # Authentication form
|       +-- main_window.py  # Main application window
|
+-- database/
|   +-- chat.db             # SQLite database (auto-generated)
|
+-- logs/
|   +-- server.log          # Rotating server logs (auto-generated)
|
+-- requirements.txt        # External dependencies
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
    created_by TEXT NOT NULL,
    invite_code TEXT NOT NULL DEFAULT ''
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

## Protocol Specification

The application uses a custom binary-framed JSON protocol. Every packet transmitted over the TCP connection is prefixed with a 4-byte unsigned integer (big-endian) representing the length of the following JSON payload.

```text
+-----------------------+----------------------------------+
|  4 bytes (uint32)     |  N bytes (UTF-8 JSON payload)    |
|  big-endian length    |  { "type": "...", ... }          |
+-----------------------+----------------------------------+
```

### Client Actions
| Type | Required Payload Fields |
|---|---|
| `register` | `username`, `password` |
| `login` | `username`, `password` |
| `logout` | None |
| `create_room` | `room` |
| `join_room` | `room` |
| `join_by_code` | `code` |
| `leave_room` | `room` |
| `delete_room` | `room` |
| `broadcast` | `room`, `message` |
| `private_message`| `target`, `message` |
| `get_rooms` | None |
| `get_users` | None |

### Server Responses & Pushes
- **Action Response**: `{ "status": "ok"|"error", "message": "..." }`
- **Room Broadcast**: `{ "type": "broadcast", "room": "...", "sender": "...", "message": "...", "timestamp": "..." }`
- **Private Message**: `{ "type": "private_message", "sender": "...", "message": "...", "timestamp": "..." }`
- **System Notification**: `{ "type": "notification", "room": "...", "message": "..." }`
- **Room History**: `{ "type": "history", "messages": [...] }`

---

## Getting Started

### Prerequisites

1. Python 3.13 or higher.
2. Install required dependencies (for GUI):
   ```bash
   pip install -r requirements.txt
   ```
3. Generate SSL certificates. Ensure OpenSSL is installed and run the following in the project root:
   ```bash
   mkdir certs
   openssl req -x509 -newkey rsa:4096 -nodes -out certs/cert.pem -keyout certs/key.pem -days 365 -subj "/CN=localhost"
   ```

### 1. Starting the Server

```bash
python -m server.server
```
Use the `--debug` flag for verbose packet-level logging.

### 2. Launching the Client

**GUI Client (Recommended):**
```bash
python -m client.gui_main
```
To pre-fill host and port details:
```bash
python -m client.gui_main --host 127.0.0.1 --port 9090
```

**CLI Client:**
```bash
python -m client.client
```

---

## Command Reference

When using the CLI client, the following commands are available:

| Command | Action |
|---|---|
| `/register <user> <pass>` | Create a new user account |
| `/login <user> <pass>` | Authenticate with the server |
| `/logout` | Terminate the current session |
| `/create <room>` | Initialize a new chat room |
| `/join <room>` | Enter a chat room and set it as active |
| `/leave [room]` | Exit the specified or currently active room |
| `/room <room>` | Switch focus to a different joined room |
| `/rooms` | Display a list of available rooms |
| `/users` | Display a list of online users |
| `/pm <user> <message>` | Send a private direct message |
| `<any text>` | Send a broadcast message to the active room |
| `/help` | Display command documentation |
| `/quit` or `/exit` | Disconnect and close the application |

---

## Testing Scenario

To verify system functionality, establish three concurrent client sessions.

1. **Start Server**: Run `python -m server.server`.
2. **Launch Clients**: Open three terminal instances running `python -m client.client` or `python -m client.gui_main`.
3. **Authentication**: Register and login as `alice`, `bob`, and `charlie`.
4. **Room Management**: Have `alice` create rooms `AI` and `General`.
5. **Session Verification**:
   - Have `alice` and `bob` join `AI`.
   - Have `charlie` join `General`.
   - Verify that broadcasts in `AI` are only visible to `alice` and `bob`.
   - Verify that private messages (`/pm charlie Hello`) are securely routed only to `charlie`.
6. **History Verification**: Have `charlie` join `AI` and confirm retrieval of prior room broadcasts.

---

### Logs

Server activities are recorded in `logs/server.log`. The logging system employs automatic rotation, capping files at 5 MB and retaining up to 3 historical backups.
