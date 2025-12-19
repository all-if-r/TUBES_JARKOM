#!/usr/bin/env python3
"""
TUBES JARKOM - Pemrograman Socket Klien
Mendukung mode HTTP, Browser, dan QoS UDP
"""

import socket
import sys
import threading
import time
import statistics
import csv
import webbrowser
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ================== UBAH IP/PORT DI SINI JIKA KONFIGURASI JARINGAN BERUBAH ==================
# Jika konfigurasi jaringan berubah, perbarui nilai-nilai ini:
PROXY_IP = "10.60.14.86"
PROXY_TCP_PORT = 8080
PROXY_UDP_PORT = 9090
SOCKET_TIMEOUT = 5.0
# ============================================================================

# Direktori dasar untuk menyimpan file (relatif ke repo, bekerja pada mesin apa pun setelah clone)
BASE_DIR = Path(__file__).resolve().parent


def print_menu():
    """Tampilkan menu utama."""
    print("\n" + "=" * 60)
    print("TUBES JARKOM - Socket Programming Client")
    print("=" * 60)
    print("Pilih mode:")
    print("  1. Mode HTTP")
    print("  2. Mode UDP (QoS)")
    print("  3. Mode Browser")
    print("=" * 60)


def http_mode():
    """Mode HTTP: kirim permintaan GET via TCP ke proxy, tampilkan respons."""
    print("\n--- Mode HTTP ---")
    try:
        path = input("Masukkan path (default '/'): ").strip()
        if not path:
            path = "/"

        # Buat socket TCP
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)

        print(f"Connecting to {PROXY_IP}:{PROXY_TCP_PORT}...")
        sock.connect((PROXY_IP, PROXY_TCP_PORT))

        # Susun dan kirim permintaan HTTP GET
        request = f"GET {path} HTTP/1.1\r\nHost: {PROXY_IP}\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode())

        # Terima respons
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        sock.close()

        # Parse respons
        response_str = response.decode(errors="ignore")
        lines = response_str.split("\r\n")

        if lines:
            # Tampilkan baris status
            print(f"\n[Status]: {lines[0]}")

            # Temukan dan tampilkan preview body
            body_start = response_str.find("\r\n\r\n")
            if body_start != -1:
                body = response_str[body_start + 4:]
                preview_len = min(500, len(body))
                print(f"\n[Body Preview] ({len(body)} bytes total):")
                print(body[:preview_len])
                if len(body) > preview_len:
                    print(f"... (truncated, {len(body) - preview_len} bytes more)")

        print("\n✓ HTTP request completed successfully.")

    except socket.timeout:
        print(f"✗ Error: Connection timeout (>{SOCKET_TIMEOUT}s)")
    except ConnectionRefusedError:
        print(f"✗ Error: Connection refused to {PROXY_IP}:{PROXY_TCP_PORT}")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")


def browser_mode():
    """Mode Browser: ambil HTML dari proxy, simpan ke file, buka di browser."""
    print("\n--- Mode Browser ---")
    try:
        # Buat socket TCP
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)

        print(f"Connecting to {PROXY_IP}:{PROXY_TCP_PORT}...")
        sock.connect((PROXY_IP, PROXY_TCP_PORT))

        # Kirim permintaan HTTP GET untuk /
        request = f"GET / HTTP/1.1\r\nHost: {PROXY_IP}\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode())

        # Terima respons
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        sock.close()

        # Parse respons HTTP
        response_str = response.decode(errors="ignore")
        body_start = response_str.find("\r\n\r\n")

        if body_start != -1:
            body = response_str[body_start + 4:]

            # Simpan ke file menggunakan path relatif repo
            output_file = BASE_DIR / "browser_result.html"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(body)

            print(f"✓ HTML saved to {output_file}")

            # Buka di browser
            browser_path = output_file.as_uri()
            webbrowser.open(browser_path)
            print("✓ Browser opened successfully.")

        else:
            print("✗ Error: Could not parse HTTP response")

    except socket.timeout:
        print(f"✗ Error: Connection timeout (>{SOCKET_TIMEOUT}s)")
    except ConnectionRefusedError:
        print(f"✗ Error: Connection refused to {PROXY_IP}:{PROXY_TCP_PORT}")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
def udp_qos_worker(client_id, num_packets, payload_size, interval_ms, results_dict):
    """
    Fungsi worker untuk tes QoS UDP.
    Mengirim N paket dan mengukur RTT, jitter, dan throughput untuk client ini.

    Argumen:
        client_id: ID unik untuk client ini
        num_packets: Jumlah paket yang dikirim (biasanya 10)
        payload_size: Ukuran payload dalam byte
        interval_ms: Interval antar paket dalam milidetik
        results_dict: Kamus bersama untuk menyimpan hasil per client
    """
    results = {
        "sent": 0,
        "received": 0,
        "rtts": [],
        "total_bytes": 0,
        "start_time": time.time(),
        "end_time": None,
    }

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(SOCKET_TIMEOUT)

        interval_sec = interval_ms / 1000.0

        for seq in range(num_packets):
            try:
                # Susun payload dengan ID client, urutan, dan timestamp
                ts_ns = int(time.time_ns())
                payload = f"cid={client_id};seq={seq};ts={ts_ns}".encode()

                # Isi hingga payload_size
                if len(payload) < payload_size:
                    payload += b"\x00" * (payload_size - len(payload))
                else:
                    payload = payload[:payload_size]

                # Kirim paket
                send_time_ns = time.time_ns()
                sock.sendto(payload, (PROXY_IP, PROXY_UDP_PORT))
                results["sent"] += 1

                # Tunggu respons
                try:
                    response, _ = sock.recvfrom(payload_size + 64)
                    recv_time_ns = time.time_ns()
                    rtt_ms = (recv_time_ns - send_time_ns) / 1_000_000
                    results["rtts"].append(rtt_ms)
                    results["received"] += 1
                    results["total_bytes"] += len(response)

                except socket.timeout:
                    # Paket hilang, tidak ada respons
                    pass

                # Tunggu interval sebelum paket berikutnya (kecuali setelah paket terakhir)
                if seq < num_packets - 1:
                    time.sleep(interval_sec)

            except Exception:
                # Kesalahan saat mengirim/menerima paket individual
                pass

        results["end_time"] = time.time()
        sock.close()

    except Exception as e:
        print(f"✗ Client {client_id} error: {e}")

    results_dict[client_id] = results


def udp_qos_mode():
    """Mode QoS UDP: uji pengiriman paket dan ukur metrik QoS."""
    print("\n--- Mode UDP (QoS) ---")

    try:
        # Ambil jumlah client
        while True:
            try:
                num_clients = int(input("Jumlah client yang diinginkan: ").strip())
                if num_clients < 1:
                    print("✗ Jumlah client harus >= 1")
                    continue
                break
            except ValueError:
                print("✗ Input tidak valid, masukkan angka")

        # Ambil mode web_server untuk penamaan CSV
        while True:
            web_server_mode = input("Mode web_server saat ini? (single/threaded): ").strip().lower()
            if web_server_mode in ("single", "threaded"):
                break
            print("✗ Pilih 'single' atau 'threaded'")

        # Ambil parameter QoS dari user
        payload_input = input("Payload size (bytes, default 256): ").strip()
        try:
            payload_size = int(payload_input) if payload_input else 256
            if payload_size < 1:
                payload_size = 256
        except ValueError:
            payload_size = 256

        interval_input = input("Interval antar packet (ms, default 50): ").strip()
        try:
            interval_ms = int(interval_input) if interval_input else 50
            if interval_ms < 1:
                interval_ms = 50
        except ValueError:
            interval_ms = 50

        print(f"\n[Konfigurasi QoS]")
        print(f"  Num clients: {num_clients}")
        print(f"  Packets per client: 10")
        print(f"  Payload size: {payload_size} bytes")
        print(f"  Interval: {interval_ms} ms")
        print()

        # Tentukan single vs multi
        client_mode = "single" if num_clients == 1 else "multi"

        # Jalankan tes QoS
        print(f"Starting UDP QoS test ({num_clients} client(s))...")

        results_dict = {}
        threads = []
        test_start = time.time()

        # Buat dan mulai thread-thread
        for cid in range(num_clients):
            thread = threading.Thread(
                target=udp_qos_worker,
                args=(cid, 10, payload_size, interval_ms, results_dict),
                daemon=False,
            )
            threads.append(thread)
            thread.start()

        # Tunggu semua thread selesai
        for thread in threads:
            thread.join()

        test_end = time.time()
        test_duration = test_end - test_start

        # Hitung statistik per-client
        print("\n" + "=" * 80)
        print("Per-Client QoS Statistics:")
        print("=" * 80)

        client_stats = {}

        for cid in sorted(results_dict.keys()):
            result = results_dict[cid]
            sent = result["sent"]
            received = result["received"]
            loss_percent = 100.0 * (sent - received) / sent if sent > 0 else 0.0

            rtts = result["rtts"]
            avg_rtt_ms = statistics.mean(rtts) if rtts else 0.0

            # Jitter: rata-rata selisih absolut antara RTT berurutan
            jitter_ms = 0.0
            if len(rtts) > 1:
                diffs = [abs(rtts[i + 1] - rtts[i]) for i in range(len(rtts) - 1)]
                jitter_ms = statistics.mean(diffs)

            # Throughput: total byte / durasi
            duration = result["end_time"] - result["start_time"] if result["end_time"] else 0.0001
            throughput_bps = (result["total_bytes"] * 8 / duration) if duration > 0 else 0.0

            client_stats[cid] = {
                "sent": sent,
                "received": received,
                "loss_percent": loss_percent,
                "avg_rtt_ms": avg_rtt_ms,
                "jitter_ms": jitter_ms,
                "throughput_bps": throughput_bps,
                "total_bytes": result["total_bytes"],
                "duration": duration,
            }

            print(f"Client {cid}:")
            print(f"  Sent: {sent}, Received: {received}, Loss: {loss_percent:.2f}%")
            print(f"  Avg RTT: {avg_rtt_ms:.3f} ms, Jitter: {jitter_ms:.3f} ms")
            print(f"  Throughput: {throughput_bps:.2f} bps ({throughput_bps/1000:.2f} kbps)")

        # Hitung statistik agregat
        print("\n" + "=" * 80)
        print("Aggregate QoS Statistics:")
        print("=" * 80)

        total_sent = sum(s["sent"] for s in client_stats.values())
        total_received = sum(s["received"] for s in client_stats.values())
        overall_loss_percent = 100.0 * (total_sent - total_received) / total_sent if total_sent > 0 else 0.0

        # Rata-rata RTT keseluruhan: rata-rata semua sampel RTT dari semua client
        all_rtts = []
        for cid in results_dict:
            all_rtts.extend(results_dict[cid]["rtts"])
        overall_avg_rtt = statistics.mean(all_rtts) if all_rtts else 0.0

        # Jitter keseluruhan: rata-rata nilai jitter per-client
        overall_jitter = statistics.mean(s["jitter_ms"] for s in client_stats.values()) if client_stats else 0.0

        # Throughput keseluruhan: jumlah byte / durasi tes keseluruhan
        total_bytes = sum(s["total_bytes"] for s in client_stats.values())
        overall_throughput_bps = (total_bytes * 8 / test_duration) if test_duration > 0 else 0.0

        print(f"Total Sent: {total_sent}, Total Received: {total_received}")
        print(f"Overall Loss: {overall_loss_percent:.2f}%")
        print(f"Overall Avg RTT: {overall_avg_rtt:.3f} ms")
        print(f"Overall Jitter: {overall_jitter:.3f} ms")
        print(f"Overall Throughput: {overall_throughput_bps:.2f} bps ({overall_throughput_bps/1000:.2f} kbps)")

        # Simpan ke CSV
        csv_filename = f"{web_server_mode}_{client_mode}.csv"
        csv_path = BASE_DIR / csv_filename

        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)

                # Header
                writer.writerow([
                    "timestamp",
                    "web_server_mode",
                    "client_mode",
                    "num_clients",
                    "packets_per_client",
                    "payload_bytes",
                    "interval_ms",
                    "client_id",
                    "sent",
                    "received",
                    "loss_percent",
                    "avg_rtt_ms",
                    "jitter_ms",
                    "throughput_bps",
                ])

                timestamp = datetime.now().isoformat()

                # Baris per-client
                for cid in sorted(client_stats.keys()):
                    stat = client_stats[cid]
                    writer.writerow([
                        timestamp,
                        web_server_mode,
                        client_mode,
                        num_clients,
                        10,
                        payload_size,
                        interval_ms,
                        cid,
                        stat["sent"],
                        stat["received"],
                        f"{stat['loss_percent']:.2f}",
                        f"{stat['avg_rtt_ms']:.3f}",
                        f"{stat['jitter_ms']:.3f}",
                        f"{stat['throughput_bps']:.2f}",
                    ])

                # Baris agregat
                writer.writerow([
                    timestamp,
                    web_server_mode,
                    client_mode,
                    num_clients,
                    10,
                    payload_size,
                    interval_ms,
                    "ALL",
                    total_sent,
                    total_received,
                    f"{overall_loss_percent:.2f}",
                    f"{overall_avg_rtt:.3f}",
                    f"{overall_jitter:.3f}",
                    f"{overall_throughput_bps:.2f}",
                ])

            print(f"\n✓ Results saved to {csv_path}")

        except Exception as e:
            print(f"✗ Error saving CSV: {e}")

    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")


def main():
    """Main entry point."""
    while True:
        print_menu()
        choice = input("Masukkan pilihan (1/2/3) atau 'q' untuk keluar: ").strip().lower()

        if choice == "q":
            print("\nTerima kasih telah menggunakan TUBES JARKOM client. Goodbye!")
            sys.exit(0)

        elif choice == "1":
            http_mode()

        elif choice == "2":
            udp_qos_mode()

        elif choice == "3":
            browser_mode()

        else:
            print("✗ Pilihan tidak valid. Silakan masukkan 1, 2, 3, atau 'q'.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProgram dihentikan oleh user.")
        sys.exit(0)
