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

def make_tls_socket(host: str, port: int, timeout: float = 15.0) -> socket.socket | None:
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
    except Exception as e:
        print(f"[ERROR TLS] {e}")
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

    sock = make_tls_socket(host, port, timeout=15.0)
    if sock is None:
        result.error = "Gagal membuat koneksi TLS"
        try:
            start_barrier.abort()
        except:
            pass
        return

    result.connected = True

    def exchange(packet: dict) -> dict | None:
        """Kirim paket dan tunggu respons (filter out notifikasi)."""
        if not send_packet(sock, packet):
            return None
        while True:
            resp = recv_packet(sock)
            if resp is None:
                return None
            # Skip notifikasi dan list paket, ambil respons utama
            if resp.get("type") not in ("user_list", "friend_list", "rooms", "room_list", "notification", "presence", "friend_request"):
                return resp

    try:
        # --- Registrasi (abaikan error jika sudah terdaftar) ---
        exchange({"type": "register", "username": username, "password": password})

        # --- Login ---
        resp = exchange({"type": "login", "username": username, "password": password})
        if resp is None or resp.get("status") != "ok":
            result.error = f"Login gagal: {resp}"
            sock.close()
            try:
                start_barrier.abort()
            except:
                pass
            return

        # --- Bergabung ke ruang menggunakan kode undangan ---
        resp = exchange({"type": "join_by_code", "code": room_code})
        if resp is None:
            result.error = "Gagal bergabung ke ruang (respons None)"
            sock.close()
            try:
                start_barrier.abort()
            except:
                pass
            return
        
        if resp.get("status") != "ok":
            result.error = f"Gagal bergabung ke ruang: {resp}"
            sock.close()
            try:
                start_barrier.abort()
            except:
                pass
            return

        room_name_resp = resp.get("room_name", "load-test-room")

        # Baca dan buang semua paket history dan notifikasi tersisa
        sock.settimeout(2.0)
        try:
            while True:
                pkt = recv_packet(sock)
                if pkt is None:
                    break
                # Skip semua non-broadcast paket
                if pkt.get("type") not in ("history", "notification", "user_list", "presence"):
                    # Jika ada broadcast yang masih tertinggal, cek apakah ada message_id
                    if pkt.get("type") == "broadcast" and pkt.get("message_id"):
                        # Bisa jadi ini adalah pesan dari user lain, simpan untuk nanti
                        break
        except Exception:
            pass
        finally:
            sock.settimeout(None)

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
                sock.settimeout(8.0)
                try:
                    matched = False
                    deadline = time.perf_counter() + 7.0
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
                        # Jika dapat broadcast dari client lain, ignorkan
                    if not matched:
                        result.messages_failed += 1
                except Exception as e:
                    result.messages_failed += 1
                finally:
                    sock.settimeout(None)

            if delay > 0:
                time.sleep(delay)

    finally:
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
        while True:
            resp = recv_packet(sock)
            if not resp: return None
            if resp.get("type") in ("user_list", "friend_list", "rooms", "room_list", "presence", "friend_request"):
                continue
            return resp

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
        print("[SETUP] Ruang sudah ada. Mencari kode undangan...")
        exchange({"type": "get_rooms"})
        # We might need to drain packets until we get room_list
        code = "N/A"
        for _ in range(10):
            r = recv_packet(sock)
            if r and r.get("type") in ("rooms", "room_list"):
                rooms = r.get("rooms", [])
                for rm in rooms:
                    if rm.get("room_name") == "load-test-room":
                        code = rm.get("invite_code", "N/A")
                        break
                break
        print(f"\n[SETUP] Kode undangan: {code}")
        print(f"\nJalankan pengujian beban dengan:\n")
        print(f"  python load_test.py --clients 10 --messages 20 --code {code}\n")
    else:
        print(f"[SETUP] Gagal membuat ruang: {resp}")

    send_packet(sock, {"type": "logout"})
    sock.close()


# ---------------------------------------------------------------------------
# Fungsi utama pengujian beban
# ---------------------------------------------------------------------------

import csv

def run_load_test(
    host: str,
    port: int,
    num_clients: int,
    num_messages: int,
    room_code: str,
    delay: float,
) -> dict:
    print(f"\n{'='*70}")
    print(f"  SKENARIO: {num_clients} Klien × {num_messages} Pesan")
    print(f"  Timeout: 120 detik")
    print(f"{'='*70}")

    results = [ClientResult(client_id=i) for i in range(num_clients)]
    threads = []
    barrier = threading.Barrier(num_clients)

    for i in range(num_clients):
        t = threading.Thread(
            target=run_simulated_client,
            args=(i, host, port, room_code, num_messages, delay, results[i], barrier),
            daemon=True,
        )
        threads.append(t)

    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    t_end = time.perf_counter()

    total_duration = t_end - t_start

    connected = sum(1 for r in results if r.connected)
    failed_connect = num_clients - connected
    total_sent = sum(r.messages_sent for r in results)
    total_failed = sum(r.messages_failed for r in results)
    all_latencies = [lat for r in results for lat in r.latencies]

    avg_lat = sum(all_latencies) / len(all_latencies) if all_latencies else 0.0
    min_lat = min(all_latencies) if all_latencies else 0.0
    max_lat = max(all_latencies) if all_latencies else 0.0
    throughput = total_sent / total_duration if total_duration > 0 else 0.0

    # Print hasil skenario
    print(f"\n  Hasil:")
    print(f"    ✓ Koneksi berhasil      : {connected}/{num_clients}")
    if failed_connect > 0:
        print(f"    ✗ Koneksi gagal         : {failed_connect}")
    print(f"    → Pesan terkirim        : {total_sent} (Gagal: {total_failed})")
    print(f"    ⏱ Latensi rata-rata    : {avg_lat:.2f} ms")
    if min_lat > 0 or max_lat > 0:
        print(f"    ⏱ Latensi min/max      : {min_lat:.2f} / {max_lat:.2f} ms")
    print(f"    📊 Throughput           : {throughput:.1f} msg/sec")
    print(f"    ⏳ Total durasi          : {total_duration:.2f} detik")
    
    # Tampilkan error jika ada
    errors = [r for r in results if r.error]
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for r in errors[:5]:  # Tampilkan max 5 error
            print(f"    - Client {r.client_id}: {r.error}")
        if len(errors) > 5:
            print(f"    ... dan {len(errors) - 5} error lainnya")
    
    return {
        "clients": num_clients,
        "messages_per_client": num_messages,
        "total_sent": total_sent,
        "total_failed": total_failed,
        "avg_lat": avg_lat,
        "min_lat": min_lat,
        "max_lat": max_lat,
        "throughput": throughput,
        "duration": total_duration
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Pengujian beban server NgeChat", 
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="""
Contoh penggunaan:
  python load_test.py --setup                    # Setup ruang uji
  python load_test.py --code ABC123              # Jalankan skenario bawaan
  python load_test.py --code ABC123 --clients 5 # Jalankan 1 skenario custom""")
    parser.add_argument("--host", default="127.0.0.1", help="Alamat server (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9090, help="Port server (default: 9090)")
    parser.add_argument("--code", default="", help="Kode undangan ruang (REQUIRED untuk run test)")
    parser.add_argument("--clients", type=int, default=0, help="Jumlah klien (default: jalankan skenario bawaan)")
    parser.add_argument("--messages", type=int, default=0, help="Jumlah pesan per klien")
    parser.add_argument("--delay", type=float, default=0.05, help="Jeda antar pesan dalam detik (default: 0.05)")
    parser.add_argument("--setup", action="store_true", help="Setup admin & ruang pengujian")

    args = parser.parse_args()

    if args.setup:
        setup_test_room(args.host, args.port)
        return

    if not args.code:
        print("[ERROR] Gunakan --code XXXXXXXX untuk menjalankan test.")
        print("         Atau gunakan --setup untuk membuat ruang baru.")
        sys.exit(1)

    room_code = args.code.strip().upper()

    # Jika user spesifik skenario custom, jalankan hanya itu
    if args.clients > 0 and args.messages > 0:
        scenarios = [(args.clients, args.messages)]
    else:
        # Default scenarios
        scenarios = [
            (5, 20),
            (10, 20),
            (20, 20),
            (50, 10),
            (100, 10)
        ]

    csv_filename = f"load_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    print(f"\n{'='*70}")
    print(f"  PENGUJIAN BEBAN - NgeChat")
    print(f"  Server: {args.host}:{args.port}")
    print(f"  Ruang: {room_code}")
    print(f"{'='*70}")
    print(f"\nMemulai {len(scenarios)} skenario...")
    print(f"Hasil akan disimpan ke: {csv_filename}\n")

    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Clients", "Messages_Per_Client", "Total_Sent", "Total_Failed",
            "Avg_Latency_ms", "Min_Latency_ms", "Max_Latency_ms",
            "Throughput_msg_sec", "Duration_sec"
        ])

        for idx, (clients, msgs) in enumerate(scenarios, 1):
            print(f"\n[{idx}/{len(scenarios)}] Skenario: {clients} klien × {msgs} pesan")
            
            stats = run_load_test(
                host=args.host,
                port=args.port,
                num_clients=clients,
                num_messages=msgs,
                room_code=room_code,
                delay=args.delay
            )
            writer.writerow([
                stats["clients"],
                stats["messages_per_client"],
                stats["total_sent"],
                stats["total_failed"],
                round(stats["avg_lat"], 2),
                round(stats["min_lat"], 2),
                round(stats["max_lat"], 2),
                round(stats["throughput"], 2),
                round(stats["duration"], 2)
            ])
            f.flush()  # Flush hasil setiap skenario
            
            # Beri jeda antar skenario agar server bisa recover
            if idx < len(scenarios):
                print(f"\n  ⏳ Jeda 3 detik sebelum skenario berikutnya...")
                time.sleep(3)
            
    print(f"\n{'='*70}")
    print(f"  ✓ SELESAI!")
    print(f"{'='*70}")
    print(f"\n📊 Hasil disimpan ke: {csv_filename}")
    print(f"\nUntuk menganalisis hasil:")
    print(f"  cat {csv_filename}")


if __name__ == "__main__":
    main()
