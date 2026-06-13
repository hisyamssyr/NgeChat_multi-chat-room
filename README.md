# NgeChat - Multi-Room Chat Application

NgeChat adalah aplikasi multi-room chat berbasis TCP socket untuk Final Project
Pemrograman Jaringan. Server ditulis dengan Python socket programming murni,
menggunakan thread per client, protokol JSON dengan length-prefix framing, TLS,
SQLite persistence, dan GUI desktop PyQt6.

## Fitur

### Fitur wajib dari task.pdf

- Authentication sederhana: register, login, logout, password di-hash.
- Online user list: panel `ONLINE USERS` diperbarui saat user login/logout.
- Room list: panel `ROOMS` menampilkan semua room, termasuk room yang terkunci.
- Chat history: 50 pesan terakhir room/PM ditampilkan saat join atau membuka chat.
- Timestamp message: setiap pesan room, PM, file, dan reaction membawa timestamp.
- Server logging: log console dan file di `logs/server.log`.

### Ketentuan Multi-Chat Room

- Mendukung banyak room.
- Satu room dapat diisi banyak client.
- Mendukung create room, join room, leave room, broadcast message, dan private
  message.
- Menggunakan TCP socket.
- Menggunakan multithreading: satu `ClientHandler` thread per koneksi.
- Semua message memakai serialization JSON dengan frame 4-byte length prefix.

### Bonus yang diimplementasikan

- Encryption/TLS: koneksi client-server berjalan di atas TLS self-signed cert.
- Database message persistence: SQLite menyimpan user, room, member, room
  messages, private messages, dan friend list.
- File transfer: kirim file kecil sampai 5 MB ke room atau private chat; penerima
  bisa memilih Download secara manual seperti aplikasi chat modern.
- Voice chat sederhana: rekam voice message dari microphone, kirim sebagai WAV,
  dan penerima bisa menekan Play langsung di bubble chat dengan progress bar.
- Emoji/reaction: tombol Emoji untuk isi pesan dan klik-kanan pada bubble chat
  untuk reaction per pesan seperti WhatsApp/Instagram. Reaction bisa diganti atau
  dibatalkan lewat menu yang sama.
- Friend system: add friend, accept/decline request, dan friend list online/offline.
- Load testing script: simulasi banyak client, throughput, dan latency.

## Struktur Singkat

```text
server/
  server.py        # TCP/TLS server, ClientHandler, packet dispatch
  protocol.py      # JSON serialization + packet builders
  room_manager.py  # online users, room membership, safe push delivery
  database.py      # SQLite persistence
  logger.py        # console/file logging
client/
  gui_main.py      # GUI entry point
  network_client.py
  protocol.py
  gui/
    login_window.py
    main_window.py
    dialogs.py
    styles.py
load_test.py
generate_cert.py
```

## Setup

Gunakan Python 3.10+.

```bash
pip install -r requirements.txt
python generate_cert.py
```

`PyAudio` digunakan untuk merekam microphone pada voice message. Jika instalasi
PyAudio bermasalah di Windows, gunakan Python yang punya wheel PyAudio tersedia
atau install PortAudio/OpenSSL tooling sesuai environment.

`generate_cert.py` membutuhkan OpenSSL di PATH. Jika OpenSSL belum tersedia,
buat manual file berikut:

```text
certs/cert.pem
certs/key.pem
```

## Menjalankan Aplikasi

Terminal 1:

```bash
python server/server.py --debug
```

Terminal 2 dan seterusnya:

```bash
python client/gui_main.py
```

Default server adalah `127.0.0.1:9090`. Bisa diubah dari login form atau env:

```bash
set CHAT_HOST=127.0.0.1
set CHAT_PORT=9090
```

## Cara Pakai GUI

1. Register account, lalu login.
2. Klik `Add Room` untuk membuat room. Invite code akan muncul setelah room
   dibuat.
3. User lain bisa klik room terkunci atau `Join with Invite Code`, lalu memasukkan
   kode room.
4. Klik room untuk chat broadcast.
5. Klik user di `ONLINE USERS` untuk private message.
6. Gunakan tombol `File` untuk kirim file. File tidak otomatis masuk folder
   penerima; penerima menekan `Download` di bubble file jika ingin menyimpan.
7. Gunakan tombol `Voice` untuk merekam voice message. Klik sekali untuk mulai
   rekam, klik `Stop` untuk mengirim.
8. Gunakan `Emoji` untuk menyisipkan emoji ke pesan. Untuk memberi reaction,
   klik-kanan bubble pesan lalu pilih emoji. Pilih emoji yang sama atau
   `Remove reaction` untuk membatalkan reaction milikmu.
9. Klik `Leave Room` untuk keluar permanen dari room.

## Desain Protokol

Semua packet:

```text
[4-byte big-endian payload length][UTF-8 JSON payload]
```

Contoh packet client ke server:

```json
{"type":"login","username":"alice","password":"secret"}
{"type":"create_room","room":"Progjar"}
{"type":"join_room","room":"Progjar","code":"ABCD1234"}
{"type":"broadcast","room":"Progjar","message":"Halo!"}
{"type":"private_message","target":"bob","message":"Ping"}
{"type":"get_users"}
{"type":"get_rooms"}
{"type":"file_transfer","scope":"room","room":"Progjar","filename":"demo.txt","data":"...base64...","kind":"file"}
{"type":"reaction","scope":"room","room":"Progjar","message_id":"room-...","emoji":"👍"}
```

Contoh packet server ke client:

```json
{"status":"ok","message":"Login successful."}
{"type":"room_list","rooms":[{"room_name":"Progjar","created_by":"alice","invite_code":"","is_member":false}]}
{"type":"user_list","users":["alice","bob"]}
{"type":"broadcast","room":"Progjar","sender":"alice","message":"Halo!","timestamp":"2026-06-13 10:00:00 UTC","message_id":"room-..."}
{"type":"history","room":"Progjar","messages":[]}
```

## Pengujian Beban

Setup room load test:

```bash
python load_test.py --setup
```

Catat invite code yang muncul, lalu jalankan:

```bash
python load_test.py --clients 20 --messages 50 --code KODE_ROOM
```

Output memuat:

- jumlah client berhasil connect,
- pesan berhasil/gagal,
- latency minimum/rata-rata/maksimum,
- throughput pesan/detik,
- file hasil `load_test_result_YYYYMMDD_HHMMSS.txt`.

## Skenario Demo yang Disarankan

1. Jalankan server dengan `--debug`, tunjukkan log.
2. Buka 3 client GUI dengan username berbeda.
3. Tunjukkan duplicate login ditolak.
4. Client 1 create room dan bagikan invite code.
5. Client 2 dan 3 join room, lalu broadcast message.
6. Tunjukkan online user list berubah saat client logout/disconnect.
7. Klik user online untuk private message.
8. Kirim file kecil dan voice note audio.
9. Kirim emoji/reaction pada salah satu bubble chat.
10. Jalankan `load_test.py` dan jelaskan hasil latency/throughput.

## Catatan Implementasi

- Server memakai TLS self-signed agar bonus encryption terpenuhi. Client menerima
  self-signed cert untuk kebutuhan demo lokal.
- SQLite memakai WAL mode dan lock Python untuk akses aman dari banyak thread.
- `RoomManager` memakai lock per socket untuk mencegah packet JSON dari beberapa
  thread saling bercampur saat broadcast/PM.
- File transfer dibatasi 5 MB agar aman untuk framing JSON dan demo kelas.
