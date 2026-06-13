import argparse
import json
import socket
import ssl
import struct
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------
# Framing (duplikat dari client/protocol.py agar skrip berdiri sendiri)
# ---------------------------------------------------------------------------

_LENGTH_FORMAT = "!I"
_LENGTH_SIZE = struct.calcsize(_LENGTH_FORMAT)
MAX_PACKET_SIZE = 16 * 1024 * 1024


def _recv_exactly(sock, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def send_packet(sock, data: dict) -> bool:
    try:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        sock.sendall(struct.pack(_LENGTH_FORMAT, len(payload)) + payload)
        return True
    except OSError:
        return False


def recv_packet(sock) -> dict | None:
    header = _recv_exactly(sock, _LENGTH_SIZE)
    if header is None:
        return None
    (length,) = struct.unpack(_LENGTH_FORMAT, header)
    if length == 0 or length > MAX_PACKET_SIZE:
        return None
    raw = _recv_exactly(sock, length)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Koneksi TLS sederhana (menerima sertifikat self-signed)
# ---------------------------------------------------------------------------

def make_tls_socket(host: str, port: int, timeout: float = 10.0) -> socket.socket | None:
    try:
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(timeout)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(raw, server_hostname=host)
        sock.connect((host, port))
        sock.settimeout(None)
        return sock
    except OSError as e:
        print(f"[KONEKSI GAGAL] {e}")
        return None


# ---------------------------------------------------------------------------
# Struktur hasil per klien
# ---------------------------------------------------------------------------

@dataclass
class ClientResult:
    client_id: int
    connected: bool = False
    messages_sent: int = 0
    messages_failed: int = 0
    latencies: list[float] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Fungsi satu klien simulasi
# ---------------------------------------------------------------------------

def run_simulated_client(
    client_id: int,
    host: str,
    port: int,
    room_code: str,
    num_messages: int,
    delay: float,
    result: ClientResult,
    start_barrier: threading.Barrier,
) -> None:
    username = f"loadtest_u{client_id:04d}"
    password = "LoadTest@1234"

    sock = make_tls_socket(host, port)
    if sock is None:
        result.error = "Gagal membuat koneksi TLS"
        start_barrier.abort()
        return

    result.connected = True

    def exchange(packet: dict) -> dict | None:
        """Kirim paket dan tunggu satu respons."""
        if not send_packet(sock, packet):
            return None
        return recv_packet(sock)

    # --- Registrasi (abaikan error jika sudah terdaftar) ---
    exchange({"type": "register", "username": username, "password": password})

    # --- Login ---
    resp = exchange({"type": "login", "username": username, "password": password})
    if resp is None or resp.get("status") != "ok":
        result.error = f"Login gagal: {resp}"
        sock.close()
        start_barrier.abort()
        return

    # --- Bergabung ke ruang menggunakan kode undangan ---
    resp = exchange({"type": "join_by_code", "code": room_code})
    if resp is None or resp.get("status") != "ok":
        # Bisa jadi respons ok diikuti history packet; coba baca satu lagi
        if resp and resp.get("type") == "history":
            pass  # ok, history sudah masuk
        elif resp is None:
            result.error = "Gagal bergabung ke ruang"
            sock.close()
            start_barrier.abort()
            return

    # Baca dan buang semua paket antrian (history, dll.)
    sock.settimeout(1.0)
    try:
        while True:
            pkt = recv_packet(sock)
            if pkt is None:
                break
    except Exception:
        pass
    sock.settimeout(None)

    room_name_resp = resp.get("room_name", "load-test-room") if resp else "load-test-room"

    # --- Tunggu semua klien siap sebelum mulai mengirim pesan ---
    try:
        start_barrier.wait(timeout=30)
    except threading.BrokenBarrierError:
        result.error = "Pengujian dibatalkan karena ada klien yang gagal siap"
        sock.close()
        return

    # --- Kirim pesan ---
    for i in range(num_messages):
        message_id = f"lt-{client_id:04d}-{i + 1}-{uuid.uuid4().hex}"
        msg_text = f"[LT-{client_id:04d}] pesan ke-{i + 1}"
        t_send = time.perf_counter()

        ok = send_packet(sock, {
            "type": "broadcast",
            "room": room_name_resp,
            "message": msg_text,
            "message_id": message_id,
        })

        if not ok:
            result.messages_failed += 1
        else:
            # Ukur latensi: tunggu echo dengan message_id yang sama.
            sock.settimeout(5.0)
            try:
                matched = False
                deadline = time.perf_counter() + 5.0
                while time.perf_counter() < deadline:
                    echo = recv_packet(sock)
                    if echo is None:
                        break
                    if (
                        echo.get("type") == "broadcast"
                        and echo.get("message_id") == message_id
                    ):
                        t_recv = time.perf_counter()
                        result.latencies.append((t_recv - t_send) * 1000)  # ms
                        result.messages_sent += 1
                        matched = True
                        break
                if not matched:
                    result.messages_failed += 1
            except Exception:
                result.messages_failed += 1
            finally:
                sock.settimeout(None)

        if delay > 0:
            time.sleep(delay)

    # --- Logout ---
    send_packet(sock, {"type": "logout"})
    sock.close()


# ---------------------------------------------------------------------------
# Mode setup: buat akun admin + ruang pengujian
# ---------------------------------------------------------------------------

def setup_test_room(host: str, port: int) -> None:
    print("\n[SETUP] Membuat akun admin dan ruang pengujian...")

    sock = make_tls_socket(host, port)
    if sock is None:
        print("[SETUP] Gagal terhubung ke server.")
        sys.exit(1)

    def exchange(packet):
        send_packet(sock, packet)
        return recv_packet(sock)

    exchange({"type": "register", "username": "loadtest_admin", "password": "Admin@1234"})
    resp = exchange({"type": "login", "username": "loadtest_admin", "password": "Admin@1234"})
    if not resp or resp.get("status") != "ok":
        print(f"[SETUP] Login admin gagal: {resp}")
        sock.close()
        sys.exit(1)

    resp = exchange({"type": "create_room", "room": "load-test-room"})
    if resp and resp.get("status") == "ok":
        code = resp.get("room_code", "N/A")
        print(f"\n[SETUP] Ruang 'load-test-room' berhasil dibuat.")
        print(f"[SETUP] Kode undangan: {code}")
        print(f"\nJalankan pengujian beban dengan:\n")
        print(f"  python load_test.py --clients 10 --messages 20 --code {code}\n")
    elif resp and "already exists" in resp.get("message", ""):
        print("[SETUP] Ruang sudah ada. Gunakan kode undangan yang sudah ada (lihat GUI atau database).")
    else:
        print(f"[SETUP] Gagal membuat ruang: {resp}")

    send_packet(sock, {"type": "logout"})
    sock.close()


# ---------------------------------------------------------------------------
# Fungsi utama pengujian beban
# ---------------------------------------------------------------------------

def run_load_test(
    host: str,
    port: int,
    num_clients: int,
    num_messages: int,
    room_code: str,
    delay: float,
) -> None:
    print(f"\n{'='*60}")
    print(f"  PENGUJIAN BEBAN SERVER NgeChat")
    print(f"  Waktu     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Server    : {host}:{port}")
    print(f"  Klien     : {num_clients}")
    print(f"  Pesan/klien: {num_messages}")
    print(f"  Kode ruang: {room_code}")
    print(f"  Jeda pesan: {delay} detik")
    print(f"{'='*60}\n")

    results = [ClientResult(client_id=i) for i in range(num_clients)]
    threads = []
    barrier = threading.Barrier(num_clients)

    # Buat semua thread
    for i in range(num_clients):
        t = threading.Thread(
            target=run_simulated_client,
            args=(i, host, port, room_code, num_messages, delay, results[i], barrier),
            daemon=True,
        )
        threads.append(t)

    # Mulai semua thread dan ukur waktu
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    t_end = time.perf_counter()

    total_duration = t_end - t_start

    # --------------- Agregasi hasil ---------------
    connected = sum(1 for r in results if r.connected)
    failed_connect = num_clients - connected
    total_sent = sum(r.messages_sent for r in results)
    total_failed = sum(r.messages_failed for r in results)
    all_latencies = [lat for r in results for lat in r.latencies]

    print(f"\n{'='*60}")
    print(f"  HASIL PENGUJIAN")
    print(f"{'='*60}")
    print(f"  Durasi total           : {total_duration:.2f} detik")
    print(f"  Klien berhasil connect : {connected} / {num_clients}")
    print(f"  Klien gagal connect    : {failed_connect}")
    print(f"  Pesan berhasil dikirim : {total_sent}")
    print(f"  Pesan gagal            : {total_failed}")

    if all_latencies:
        avg_lat = sum(all_latencies) / len(all_latencies)
        min_lat = min(all_latencies)
        max_lat = max(all_latencies)
        print(f"  Latensi rata-rata      : {avg_lat:.2f} ms")
        print(f"  Latensi minimum        : {min_lat:.2f} ms")
        print(f"  Latensi maksimum       : {max_lat:.2f} ms")

    if total_duration > 0:
        throughput = total_sent / total_duration
        print(f"  Throughput             : {throughput:.1f} pesan/detik")

    print(f"{'='*60}\n")

    # --------------- Tampilkan error per klien ---------------
    errors = [(r.client_id, r.error) for r in results if r.error]
    if errors:
        print(f"[!] Klien yang mengalami error ({len(errors)} klien):")
        for cid, err in errors[:10]:  # tampilkan maksimal 10
            print(f"    Klien {cid:04d}: {err}")
        if len(errors) > 10:
            print(f"    ... dan {len(errors) - 10} lainnya.")
        print()

    # --------------- Simpan hasil ke file ---------------
    output_file = f"load_test_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"NgeChat Load Test Result\n")
        f.write(f"Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Konfigurasi:\n")
        f.write(f"  Server         : {host}:{port}\n")
        f.write(f"  Jumlah klien   : {num_clients}\n")
        f.write(f"  Pesan/klien    : {num_messages}\n")
        f.write(f"  Kode ruang     : {room_code}\n")
        f.write(f"  Jeda pesan     : {delay} detik\n\n")
        f.write(f"Hasil:\n")
        f.write(f"  Durasi total           : {total_duration:.2f} detik\n")
        f.write(f"  Klien berhasil connect : {connected} / {num_clients}\n")
        f.write(f"  Klien gagal connect    : {failed_connect}\n")
        f.write(f"  Pesan berhasil dikirim : {total_sent}\n")
        f.write(f"  Pesan gagal            : {total_failed}\n")
        if all_latencies:
            f.write(f"  Latensi rata-rata      : {avg_lat:.2f} ms\n")
            f.write(f"  Latensi minimum        : {min_lat:.2f} ms\n")
            f.write(f"  Latensi maksimum       : {max_lat:.2f} ms\n")
        if total_duration > 0:
            f.write(f"  Throughput             : {throughput:.1f} pesan/detik\n")

    print(f"[INFO] Hasil disimpan ke: {output_file}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pengujian beban server NgeChat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="Alamat server (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9090, help="Port server (default: 9090)")
    parser.add_argument("--clients", type=int, default=10, help="Jumlah klien simulasi (default: 10)")
    parser.add_argument("--messages", type=int, default=20, help="Jumlah pesan per klien (default: 20)")
    parser.add_argument("--code", default="", help="Kode undangan ruang pengujian")
    parser.add_argument("--delay", type=float, default=0.05, help="Jeda antar pesan dalam detik (default: 0.05)")
    parser.add_argument("--setup", action="store_true", help="Buat akun admin dan ruang pengujian")

    args = parser.parse_args()

    if args.setup:
        setup_test_room(args.host, args.port)
        return

    if not args.code:
        print("[ERROR] Kode undangan ruang diperlukan. Gunakan --code XXXXXXXX")
        print("        Jalankan --setup terlebih dahulu untuk mendapatkan kode.")
        sys.exit(1)

    run_load_test(
        host=args.host,
        port=args.port,
        num_clients=args.clients,
        num_messages=args.messages,
        room_code=args.code.strip().upper(),
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
