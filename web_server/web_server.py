#!/usr/bin/env python3


import socket
import threading
import time
import sys
from datetime import datetime
from pathlib import Path

# ================== UBAH PORT DI SINI JIKA DIPERLUKAN ==================
# Jika port sudah digunakan, ubah di sini:
# ===============================================================
TCP_PORT = 8000
UDP_PORT = 9000
SOCKET_TIMEOUT = 30
# ===============================================================

# Menyelesaikan path relatif terhadap file ini
BASE_DIR = Path(__file__).resolve().parent
HTML_FILE_PATH = BASE_DIR.parent / "test-tubes-jarkom.html"


def print_menu():
    print("\n" + "=" * 70)
    print("TUBES JARKOM - Web Server")
    print("=" * 70)
    print("Pilih mode server:")
    print("  1. Single-threaded mode")
    print("  2. Multi-threaded mode (threaded)")
    print("=" * 70)


def load_html_file():
    try:
        with open(HTML_FILE_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"✓ HTML file loaded ({len(content)} bytes)")
        return True, content
    except FileNotFoundError:
        print(f"✗ HTML file not found: {HTML_FILE_PATH}")
        content = "<html><body><h1>404 - File Not Found</h1></body></html>"
        return False, content
    except Exception as e:
        print(f"✗ Error loading HTML: {e}")
        content = "<html><body><h1>500 - Server Error</h1></body></html>"
        return False, content


def parse_http_request(request_data):
    try:
        lines = request_data.split('\r\n')
        if not lines:
            return None

        request_line = lines[0]
        parts = request_line.split()

        if len(parts) < 2:
            return None

        method = parts[0]
        path = parts[1]

        if method != "GET":
            return None

        return path
    except Exception:
        return None


def generate_http_response(status_code, content):
    status_messages = {
        200: "OK",
        404: "Not Found",
        500: "Internal Server Error",
    }

    status_msg = status_messages.get(status_code, "Unknown")
    content_bytes = content.encode('utf-8')
    content_length = len(content_bytes)

    response = (
        f"HTTP/1.1 {status_code} {status_msg}\r\n"
        f"Content-Type: text/html\r\n"
        f"Content-Length: {content_length}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{content}"
    )

    return response


def handle_tcp_client(client_socket, client_address, html_content):
    start_time = time.time()
    client_ip = client_address[0]
    client_port = client_address[1]
    request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    try:
        client_socket.settimeout(SOCKET_TIMEOUT)

        # Terima permintaan HTTP
        request_data = client_socket.recv(4096).decode('utf-8', errors='ignore')

        if not request_data:
            print(f"[{request_time}] [{client_ip}:{client_port}] Empty request")
            return

        # Mengurai path permintaan
        path = parse_http_request(request_data)

        if path is None:
            response = generate_http_response(400, "<html><body><h1>400 - Bad Request</h1></body></html>")
            resource = "INVALID"
            status_code = 400
        elif path in ["/", "/index.html"]:
            # Kembalikan file HTML
            response = generate_http_response(200, html_content)
            resource = path
            status_code = 200
        else:
            # Path tidak ditemukan
            response = generate_http_response(404, "<html><body><h1>404 - Not Found</h1></body></html>")
            resource = path
            status_code = 404

        # Kirim respons
        client_socket.sendall(response.encode('utf-8'))

        # Hitung metrik
        processing_time = (time.time() - start_time) * 1000  # milliseconds
        response_size = len(response.encode('utf-8'))

        # Catat transaksi
        print(
            f"[{request_time}] [TCP] Client: {client_ip}:{client_port} | "
            f"Resource: {resource} | Status: {status_code} | "
            f"Response Size: {response_size} bytes | Processing: {processing_time:.2f} ms"
        )

    except socket.timeout:
        print(f"[{request_time}] [{client_ip}:{client_port}] Timeout after {SOCKET_TIMEOUT}s")
    except Exception as e:
        print(f"[{request_time}] [{client_ip}:{client_port}] Error: {e}")
    finally:
        try:
            client_socket.close()
        except Exception:
            pass


def tcp_server_loop(is_multithreaded, html_content):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind(("0.0.0.0", TCP_PORT))
        server_socket.listen(5)
        print(f"\n✓ TCP Server listening on 0.0.0.0:{TCP_PORT} ({'Multi-threaded' if is_multithreaded else 'Single-threaded'})")
        print(f"  Mode: {'Parallel request handling' if is_multithreaded else 'Sequential request handling'}")

        while True:
            try:
                client_socket, client_address = server_socket.accept()

                if is_multithreaded:
                    # Multi-threaded: buat thread pekerja
                    thread = threading.Thread(
                        target=handle_tcp_client,
                        args=(client_socket, client_address, html_content),
                        daemon=True
                    )
                    thread.start()
                else:
                    # Single-threaded: tangani secara berurutan
                    handle_tcp_client(client_socket, client_address, html_content)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"✗ Error accepting TCP client: {e}")

    except OSError as e:
        print(f"✗ TCP Socket error: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        server_socket.close()
        print("✓ TCP Server stopped")


def udp_echo_server_loop():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind(("0.0.0.0", UDP_PORT))
        server_socket.settimeout(1.0)  # Untuk penghentian yang rapi
        print(f"✓ UDP Echo Server listening on 0.0.0.0:{UDP_PORT}")

        while True:
            try:
                data, client_address = server_socket.recvfrom(65535)
                client_ip = client_address[0]
                client_port = client_address[1]
                packet_size = len(data)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                # Kirim balik data segera (tanpa logika retransmisi)
                server_socket.sendto(data, client_address)

                # Catat paket
                print(
                    f"[{timestamp}] [UDP] Source: {client_ip}:{client_port} | "
                    f"Packet Size: {packet_size} bytes"
                )

            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"✗ UDP error: {e}")

    except OSError as e:
        print(f"✗ UDP Socket error: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        server_socket.close()
        print("✓ UDP Echo Server stopped")


def main():
    print_menu()

    # Ambil pilihan pengguna
    while True:
        choice = input("Masukkan pilihan (1 atau 2): ").strip()
        if choice in ("1", "2"):
            break
        print("✗ Pilihan tidak valid. Masukkan 1 atau 2.")

    is_multithreaded = choice == "2"

    # Muat file HTML
    success, html_content = load_html_file()

    # Cetak info startup
    print("\n" + "=" * 70)
    print("TUBES JARKOM Web Server")
    print("=" * 70)
    print(f"Mode: {'Multi-threaded (threaded)' if is_multithreaded else 'Single-threaded'}")
    print(f"  • Single-threaded: Handles TCP requests one at a time, sequentially")
    print(f"  • Multi-threaded: Each TCP request is handled in a separate thread")
    print(f"TCP Port: {TCP_PORT}")
    print(f"UDP Port: {UDP_PORT}")
    print(f"HTML File: {HTML_FILE_PATH}")
    print("Press Ctrl+C to stop servers")
    print("=" * 70)

    # Jalankan server UDP di thread latar (background)
    udp_thread = threading.Thread(target=udp_echo_server_loop, daemon=True)
    udp_thread.start()

    # Jalankan server TCP di thread utama
    try:
        tcp_server_loop(is_multithreaded, html_content)
    except KeyboardInterrupt:
        print("\n\nShutting down servers...")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nServer stopped by user.")
        sys.exit(0)

