# NgeChat - Multi-Chat Room Application

NgeChat adalah aplikasi *client-server* berbasis GUI untuk berkirim pesan waktu nyata (real-time). Proyek ini dirancang untuk menangani konkurensi tinggi, komunikasi yang aman menggunakan enkripsi TLS/SSL, dan pengiriman pesan berkecepatan tinggi dengan menggunakan *custom wire protocol* berbasis TCP.

Berikut adalah penjelasan lengkap mengenai sistem NgeChat yang mencakup seluruh komponen dari fitur hingga *low-level implementation* pada sisi *backend*.

---

## 1. Penjelasan Lengkap Fitur Aplikasi

Aplikasi NgeChat dilengkapi dengan beragam fitur *modern messaging*:

1. **Autentikasi & Manajemen Akun**: Pengguna dapat mendaftarkan akun (Register) dan masuk (Login). Kata sandi disimpan dengan aman menggunakan *hashing* (SHA-256).
2. **Sistem Multi-Chat Room**:
   - Pengguna dapat membuat Ruang Obrolan (Room) baru yang otomatis di-generate *Invite Code* (kode undangan).
   - Bergabung ke ruangan menggunakan *Room Name* atau *Invite Code*.
   - Notifikasi *real-time* saat ada pengguna yang bergabung (join), keluar (leave), atau admin menghapus room.
3. **Private Messaging (Japri)**: Mendukung pengiriman pesan secara langsung (1-on-1) ke pengguna lain yang terdaftar.
4. **File Transfer & Voice Notes**:
   - Mendukung pengiriman file dan pesan suara hingga ukuran 5 MB.
   - Pengiriman file dapat dilakukan baik di dalam lingkup *Room* maupun *Private Message*. File dienkode menggunakan Base64 selama transit dan disimpan ke dalam sistem file server.
5. **Sistem Pertemanan (Friend System)**: 
   - Fitur untuk mengirim permintaan pertemanan, menerima (*accept*), dan menolak (*decline*) *friend request*.
   - Melacak status *online/offline* dari teman secara *real-time*.
6. **Reactions / Emoji Reactions**: Pengguna dapat memberikan atau menghapus reaksi emoji pada pesan spesifik (*message_id*) secara *real-time*, baik di *Room* maupun *Private Message*.
7. **Persistent Chat History**: Semua pesan (teks, lampiran, dan reaksi) disimpan ke dalam *database* (SQLite), sehingga riwayat obrolan tidak hilang meskipun klien atau server dimatikan.

---

## 2. Tech Stack dan Arsitektur

NgeChat dibangun dengan menggunakan perpaduan teknologi yang berfokus pada kecepatan dan kontrol level rendah jaringan.

**Tech Stack:**
- **Bahasa Pemrograman**: Python 3.
- **Frontend / GUI**: `PyQt6` (berbasis Qt framework untuk UI yang asinkron dan reaktif).
- **Audio Processing**: `PyAudio` untuk merekam dan memutar *voice notes*.
- **Networking**: `socket` (Raw TCP Sockets) dan `ssl` untuk komunikasi jaringan E2E (*Transport-Layer*).
- **Database**: SQLite3 dengan mode **WAL** (*Write-Ahead Logging*) untuk performa konkurensi *read/write* yang sangat optimal.

**Arsitektur (Client-Server & Thread-per-Client):**
- Menggunakan arsitektur terpusat (*Centralized Server*).
- **Thread-per-Client Model**: Setiap kali klien baru terkoneksi, server akan melakukan *spawn* (membuat) satu *thread* baru khusus (`ClientHandler`) untuk memproses *I/O blocking* (seperti `recv()`).
- **In-Memory State Manager**: Server menggunakan sebuah objek Singleton-like (`RoomManager`) di memori untuk mencatat relasi antar-*socket*, pengguna yang *online*, dan *membership* setiap ruangan. State di memori ini mempercepat pengiriman pesan *broadcast* tanpa harus terus-menerus melakukan *query* ke database.

---

## 3. Alur Komunikasi, Enkripsi, dan Database

### Alur Komunikasi & Protokol (Custom Wire-Protocol)
Aplikasi ini tidak menggunakan HTTP, melainkan membangun protokol pesannya sendiri menggunakan mekanisme pembingkaian (*framing*) **Length-Prefixed JSON**.
- **Framing**: Setiap paket yang dikirim di jaringan akan selalu diawali oleh **4-byte *header*** (`!I` - *big-endian unsigned integer*) yang merepresentasikan panjang (ukuran) payload JSON yang akan menyusul.
- Ini menyelesaikan masalah klasik pada TCP yaitu *Stream Boundary* (paket yang bergabung atau terpotong di tengah jaringan). Server dan klien selalu tahu persis berapa banyak byte yang harus dibaca dari *buffer* untuk mendapatkan 1 pesan JSON yang utuh.

### Enkripsi Keamanan (TLS/SSL)
Semua lalu lintas TCP mentah (raw TCP) dibungkus (di-*wrap*) menggunakan `ssl.create_default_context()`.
- Server memuat `cert.pem` dan `key.pem` untuk membentuk koneksi TLS. 
- Ini memastikan bahwa payload (pesan, kredensial login, transfer file) terenkripsi dari titik-ke-titik (*transport layer*) sehingga mustahil di-*sniff* atau dibaca secara *plaintext* oleh *Man-in-the-Middle* (MitM).

### Database Schema & Flow
- Database didesain secara relasional (RDBMS) menggunakan SQLite (file `chat.db`). Skema databasenya dioptimalkan dengan prinsip PDM (Physical Data Model), memiliki entitas `users`, `rooms`, `room_members`, `messages`, `private_messages`, `attachments`, `reactions`, dan `friends`.
- **Mode WAL (Write-Ahead Logging)** diaktifkan menggunakan pragma `PRAGMA journal_mode=WAL;`. Ini mengizinkan proses *Read* dan *Write* dapat terjadi secara berbarengan (*concurrent*), yang mana sangat krusial pada aplikasi *chat server* dengan load tinggi.
- *Thread-safety* pada penulisan diatur di level aplikasi menggunakan `threading.Lock()` yang membungkus semua query `INSERT/UPDATE/DELETE`, memastikan *database lock* SQLite tidak menyebabkan server *crash*.

---

## 4. Penjelasan Super Lengkap Fungsi-Fungsi Backend

Komponen utama backend terletak di folder `server/`, yang membagi tugas menjadi beberapa modul utama:

### A. `server/server.py` (Core Server Engine)
Modul ini adalah jantung dari program server yang mengelola *lifecycle* *networking*.
- `ChatServer`: Class utama yang mengikat (binding) socket ke alamat `0.0.0.0:9090` dan membungkusnya dengan *SSL Context*. Memiliki *main loop* `.start()` yang memblokir program untuk mendengarkan `accept()`. Ketika ada klien terhubung, ia melempar socket tersebut ke dalam `threading.Thread(target=handler.run)`.
- `ClientHandler`: Class pengelola untuk SATU klien yang terhubung.
  - `run()`: Infinite loop yang terus-menerus memanggil `recv_packet()`. Jika paket kosong atau terputus, ia akan masuk ke `_cleanup()`.
  - `_handle_packet()`: Router internal yang mendistribusikan *payload* JSON ke fungsi-fungsi spesifik (seperti HTTP routing).
  - **Autentikasi**: `_handle_register`, `_handle_login`, `_handle_logout`. Terhubung ke enkripsi DB untuk verifikasi.
  - **Manajemen Room**: `_handle_create_room`, `_handle_join_room`, `_handle_join_by_code`, `_handle_leave_room`, `_handle_delete_room`. Mengontrol izin bergabung dan membuat kode invite.
  - **Messaging**: `_handle_broadcast` (kirim ke room), `_handle_private_message` (kirim PM). Keduanya memanggil DB untuk simpan riwayat, lalu mendistribusikan *push JSON* ke soket-soket *online* target.
  - `_handle_file_transfer`: Melakukan dekode Base64, memvalidasi limit 5MB, menyimpannya di file sistem (`uploads/`), mencatat *path* lampiran di database, dan mengirimkan notifikasi *transfer* ke *receiver*.
  - `_handle_reaction`: Menulis reaksi emoji ke tabel `reactions` berdasarkan parameter `action` ('set' atau 'remove').

### B. `server/database.py` (Data Access Layer)
Satu-satunya class yang berinteraksi langsung dengan SQLite. Semua metodologi dibungkus oleh `with self._lock:` untuk menjamin antrean tulis aman.
- `initialise()`: Membuat koneksi `sqlite3.connect(check_same_thread=False)`, mengaktifkan pragma WAL dan FK, lalu mengeksekusi migrasi skema tabel secara otomatis.
- **User Ops**: `register_user()`, `validate_login()` yang melakukan algoritma *hash* SHA-256 pada parameter password sebelum membandingkan/menyimpannya.
- **Room Ops**: `create_room()`, `add_room_member()`, `check_room_code()`, `get_all_rooms()`. Digunakan untuk memvalidasi dan memuat data ruangan yang diikuti *user*.
- **Message Ops**: `save_message()`, `save_private_message()` menghasilkan UUID (seperti `msg-xxx`) unik. `get_room_history()` / `get_private_history()` mengambil history (default 50 pesan terakhir) dengan urutan ASC.
- `_attach_message_metadata()`: Mengkombinasikan metadata (Attachment dan Reactions) pada saat sistem meminta *chat history*.
- **Friends Ops**: `send_friend_request()`, `accept_friend_request()`, `remove_friend()`. Mengontrol *state machine* tabel pertemanan dari status `pending` ke `accepted`.

### C. `server/protocol.py` (Protokol dan Framing Layer)
Modul utilitas jaringan yang di-*share* secara konseptual antara server dan klien.
- `send_packet(sock, data)`: Mengubah dictionary Python ke *JSON String*, mengubahnya ke byte `utf-8`, menghitung panjang byte-nya, dan melakukan *pack* (menggabungkan struct *header length* 4-byte dan *payload* utuh) untuk dikirim ke jaringan.
- `recv_packet(sock)`: Menarik pasti 4-byte pertama menggunakan fungsi *helper* `_recv_exactly`, melakukan *unpack* integer, lalu membaca sisa aliran data TCP berdasarkan jumlah length tersebut untuk men-*decode* JSON-nya dengan aman tanpa melanggar *Stream Boundaries*.
- `validate_packet(packet)`: Skema validasi. Mengecek `REQUIRED_FIELDS` seperti *schema-validator*. Apabila paket `join_room` tidak punya atribut `room`, ia akan memicu eksepsi `PacketError`.
- Kumpulan fungsi `make_*_push()`: *Factory* JSON yang memastikan struktur respons *server-to-client* konsisten bentuknya.

### D. `server/room_manager.py` (In-Memory State & Routing)
Agar tidak terus membaca database untuk mengecek siapa yang online.
- `_online_users`: Hashmap / Dictionary berisi pemetaan `{"username": <socket_object>}`.
- `_room_members`: Set pemetaan pengguna yang sedang aktif melihat sebuah obrolan `{"room_A": set("user1", "user2")}`.
- `broadcast_to_room()`: Melakukan iterasi dari `_room_members`, mengambil soket milik tiap *username*, lalu mengirim JSON paket secara terpisah ke tiap-tiap soket.
- Melibatkan mekanisme proteksi pengiriman dengan memegang `threading.Lock()` per pengguna (*send lock*) untuk menjamin jika ada dua pesan dikirimkan ke satu soket secara paralel, aliran byte-nya tidak tumpang tindih.

---

## 5. Skema Pengujian (Testing) dan Cara Kerja Kode Program

Untuk memvalidasi arsitektur konkuren dan kinerja *Write-Ahead Logging*, server telah diuji menggunakan skema simulasi beban tinggi.

**Skema Pengujian (Load Testing):**
- Diotomatisasi melalui file skrip **`testing/load_test.py`**.
- Skrip ini akan membuat puluhan atau ratusan *thread* simulasi klien fiktif. Setiap klien melakukan: TLS Handshake -> Register -> Login -> Masuk Room (Join via Invite Code) -> Synchronized Barrier (menunggu semua klien siap bersamaan).
- Secara bersamaan, setiap klien membanjiri (*flooding*) server dengan fungsi `broadcast` (contoh: 100 klien mengirim masing-masing 20 pesan tanpa jeda waktu *delay*).
- Skrip mencatat **Latensi Jaringan** (dengan mekanisme pengecekan echo balik `message_id`), menghitung angka throughput (*messages per second*), dan *Failure rate*. Semua *metrics* diekspor dalam bentuk `.csv` untuk analisa komprehensif.

**Cara Kerja Siklus Program (End-to-End Flow):**
1. **Server Start**: Jalankan `server/server.py`. Server *bind port*, menyalakan SSL, menyiapkan *database schema* (WAL).
2. **Klien Connect**: Aplikasi PyQt mengirim permintaan TCP. Keduanya berjabat tangan (*SSL Handshake*).
3. **Loop Utama (I/O)**: Server memutar `ClientHandler`. Klien memutar thread *receiver* (`client.receive_thread`).
4. **Action (Contoh Kirim Pesan)**:
   - Klien UI mengumpulkan teks input dan memanggil `send_packet()`.
   - Payload JSON dirakit, panjang ukuran *(size)* ditambahkan di depan, dikirim via jaringan.
   - Fungsi `_recv_exactly()` server menerima byte, merekonstruksi JSON.
   - `_handle_packet()` mendeteksi *type* "broadcast", memvalidasi hak otorisasi *(require login)*.
   - `Database.save_message()` mengunci proses (*Locking*), menulis pesan ke SQLite, melepas kunci.
   - Server merakit JSON respon menggunakan `make_broadcast_push()`.
   - `RoomManager` mencari siapa saja soket di ruang itu, lalu mengirimkan (push) respons via jaringan.
   - Klien GUI mendapat sinyal (*Qt Signal/Slot*), dan menempelkan bubble *chat* di antarmuka obrolan.

---

## 6. Detail Logic & Flow Code (Line-by-Line / Step-by-Step)

Untuk pemahaman lebih dalam terkait logika operasional, berikut adalah penjelasan baris per baris (*line-by-line*) disertai potongan kodenya dari fungsi-fungsi paling kritikal di *backend*:

### A. `ClientHandler.run()` (Loop Utama Klien)
**Lokasi:** `server/server.py`
Fungsi ini berjalan di dalam thread terpisah untuk setiap klien yang terhubung, menjaga agar koneksi satu pengguna tidak mengganggu pengguna lain.

```python
def run(self) -> None:
    logger.info("New connection from %s:%d", *self._addr)
    try:
        while self._running:
            # 1. Memblokir (block) thread ini menunggu data dari socket TCP
            packet = recv_packet(self._sock)

            # 2. Jika koneksi terputus tiba-tiba atau clean disconnect
            if packet is None:
                logger.info("Client %s:%d disconnected.", *self._addr)
                break

            # 3. Jika paket kosong (gagal decode JSON)
            if not packet:
                self._send_packet(
                    make_response("error", "Empty or malformed packet.")
                )
                continue

            # 4. Lempar ke router internal untuk diidentifikasi tipe perintahnya
            self._handle_packet(packet)

    except Exception as exc:
        # 5. Mencegah crash jika terjadi error yang tidak terduga pada thread ini
        logger.error(
            "Unhandled exception for %s:%d — %s", *self._addr, exc, exc_info=True
        )
    finally:
        # 6. Menjamin pelepasan resource (socket ditutup) dan user dihapus dari RoomManager
        self._cleanup()
```

### B. Logika Framing (`send_packet` & `recv_packet`)
**Lokasi:** `server/protocol.py`
Fungsi ini menjamin transmisi byte TCP yang murni bisa menjadi JSON terstruktur tanpa terkena masalah *Stream Boundary*.

**1. `send_packet` (Mengirim Data)**
```python
def send_packet(sock, data: dict) -> bool:
    try:
        # 1. Mengonversi dictionary ke JSON String, lalu merubahnya jadi byte (UTF-8)
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        
        # 2. Menggabungkan 4-byte header (panjang byte payload) menggunakan struct '!I'
        #    dengan payload utama, lalu mengirim keseluruhannya ke socket
        sock.sendall(struct.pack(_LENGTH_FORMAT, len(payload)) + payload)
        return True
    except (OSError, BrokenPipeError) as exc:
        logger.debug("send_packet failed: %s", exc)
        return False
```

**2. `recv_packet` (Menerima Data)**
```python
def recv_packet(sock) -> dict | None:
    # 1. Menarik persis 4 byte pertama yang berisi informasi panjang payload
    header = _recv_exactly(sock, _LENGTH_SIZE)
    if header is None: return None

    # 2. Menerjemahkan 4-byte tersebut menjadi angka integer desimal
    (length,) = struct.unpack(_LENGTH_FORMAT, header)

    if length == 0: return {}
    
    # 3. Mencegah eksploitasi memori berlebih (buffer overflow / DDoS)
    if length > MAX_PACKET_SIZE: # 16 MB limit
        return None

    # 4. Menarik tepat sejumlah byte payload yang dijanjikan oleh header
    raw = _recv_exactly(sock, length)
    if raw is None: return None

    try:
        # 5. Decode payload byte kembali jadi objek python Dictionary
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {} 
```

### C. `_handle_broadcast()` (Logika Kirim Pesan ke Ruang)
**Lokasi:** `server/server.py`
Dieksekusi saat klien mengirim pesan obrolan ke dalam suatu ruangan.

```python
def _handle_broadcast(self, packet: dict) -> None:
    # 1. Tolak eksekusi jika user belum login
    if not self._require_login(): return

    # 2. Ambil nilai dari JSON dan bersihkan white-space berlebih
    room_name = packet["room"].strip()
    message = packet["message"].strip()

    if not message:
        self._send_err("Message cannot be empty.")
        return

    # 3. Validasi ke memori apakah user benar-benar ada di dalam room tersebut
    if not self._rooms.is_in_room(self._username, room_name):
        self._send_err(f"You are not in room '{room_name}'. Join the room first.")
        return

    # 4. Generate timestamp server
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    message_id = packet.get("message_id")
    
    # 5. Tulis riwayat pesan ke dalam Database SQLite.
    #    Database me-return ID Unik Pesan yang berhasil disimpan.
    message_id = self._db.save_message(
        room_name, self._username, message, timestamp, message_id=message_id
    )
    
    # 6. Rakit respons JSON untuk disebarkan kembali
    push = make_broadcast_push(
        room_name, self._username, message, timestamp, message_id=message_id
    )
    
    # 7. Memerintahkan RoomManager mendistribusikan secara asinkron ke semua anggota
    self._rooms.broadcast_to_room(room_name, push)
```

### D. `_handle_file_transfer()` (Pengiriman File Base64)
**Lokasi:** `server/server.py`
Mengelola aliran pengiriman file dan pesan suara (*voice notes*).

```python
def _handle_file_transfer(self, packet: dict) -> None:
    if not self._require_login(): return

    scope = packet.get("scope", "").strip().lower()
    filename = _safe_filename(packet.get("filename", "attachment.bin"))
    kind = packet.get("kind", "file").strip().lower()

    try:
        # 1. Decode teks Base64 JSON menjadi data byte mentah (raw bytes)
        raw = base64.b64decode(packet.get("data", ""), validate=True)
    except (binascii.Error, ValueError):
        self._send_err("File data is not valid base64.")
        return

    # 2. Validasi keamanan ukuran maksimal file adalah 5 MB
    if len(raw) > MAX_TRANSFER_BYTES:
        self._send_err("File is too large. Maximum size is 5 MB.")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # 3. Simpan byte aktual menjadi file asli di hardisk (folder /uploads)
    #    Ini meringankan beban database dari menyimpan BLOB berlebih.
    stored_path = _store_transfer(self._username, filename, raw)
    
    message_text = f"[{'Voice note' if kind == 'voice' else 'File'}] {filename}"
    encoded = base64.b64encode(raw).decode("ascii") # Encode balik untuk disebar

    if scope == "room":
        room_name = packet.get("room", "").strip()
        # 4. Simpan placeholder pesan (misal "[File] laporan.pdf") ke log messages obrolan
        message_id = self._db.save_message(room_name, self._username, message_text, timestamp)
        
        # 5. Tautkan ID Pesan ke metadata riwayat lampiran
        self._db.save_attachment(message_id, filename, encoded, len(raw), kind, stored_path)
        
        # 6. Kirim file tersebut ke semua orang di room tersebut
        push = make_file_transfer_push(
            scope="room", room=room_name, sender=self._username, filename=filename,
            data=encoded, timestamp=timestamp, size=len(raw), kind=kind, message_id=message_id,
        )
        self._rooms.broadcast_to_room(room_name, push)
```

### E. `Database.save_message()` (Penulisan Thread-Safe Database)
**Lokasi:** `server/database.py`
Melindungi database SQLite dari potensi *corrupt* akibat konkurensi (tabrakan thread).

```python
def save_message(self, room_name: str, sender: str, message: str, timestamp: str = None, message_id: str = None) -> str:
    if timestamp is None:
        timestamp = self._now_utc()
    if not message_id:
        # 1. Menghasilkan ID unik seperti 'msg-xxx-UUIDv4'
        message_id = self._new_message_id("room")

    # 2. AKUISISI LOCK (KUNCI MUTEX)
    #    Jika ada 100 thread masuk bersaman, 99 akan menunggu (block)
    #    di baris ini hingga 1 thread yang memegang kunci selesai menulis.
    with self._lock:
        try:
            # 3. Eksekusi query INSERT secara parameterisasi `(?)` 
            #    Mencegah peretasan berbentuk serangan SQL Injection!
            self._conn.execute(
                "INSERT INTO messages (message_id, room_name, sender, message, timestamp)"
                " VALUES (?, ?, ?, ?, ?)",
                (message_id, room_name, sender, message, timestamp),
            )
            # 4. Mengonfirmasi hasil write ke disk (`chat.db`)
            self._conn.commit()
            return message_id
            
        except sqlite3.Error as exc:
            logger.error("save_message DB error: %s", exc)
            return message_id
    
    # 5. Kunci `self._lock` akan otomatis dilepas tepat saat keluar dari blok `with`
```

---
*Dokumentasi ini ditulis untuk menjelaskan seluruh kedalaman teknikal dan arsitektur pengembangan NgeChat Multi-Chat Room Application.*

