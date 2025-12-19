#!/usr/bin/env python3

import socket
import threading
import logging
import time
from datetime import datetime
from urllib.parse import urlparse
from collections import defaultdict
import json


CLIENT_BIND_IP = "0.0.0.0"           
CLIENT_TCP_PORT = 8080               
CLIENT_UDP_PORT = 9090               
WEB_SERVER_IP = "10.60.14.89"        #ip laptop ryan
WEB_SERVER_TCP_PORT = 8000           
WEB_SERVER_UDP_PORT = 9000           
SOCKET_TIMEOUT = 8                   # 5-10 rekomendasinya


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler('proxy_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class HTTPCache:
    """Cache respons HTTP dalam memori dengan penyaringan respons HTTP 200 OK"""
    
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()
    
    def get(self, path):
        """Mendapatkan respons dari cache (mengembalikan None jika tidak ditemukan atau telah kadaluwarsa)"""
        with self.lock:
            if path in self.cache:
                return self.cache[path]
        return None
    
    def set(self, path, response):
        """Simpan respons dalam cache jika responsnya adalah HTTP 200 OK."""
        try:
            # Ambil kode status dari respons
            if response.startswith("HTTP/1.1 200"):
                with self.lock:
                    self.cache[path] = response
                return True
        except Exception as e:
            logger.error(f"Error caching response: {e}")
        return False
    
    def clear(self):
        """Hapus semua cache"""
        with self.lock:
            self.cache.clear()
    
    def get_stats(self):
        """Buat dapat statisik cache"""
        with self.lock:
            return {"cached_paths": len(self.cache), "paths": list(self.cache.keys())}


class HTTPProxy:
    """Komponen TCP HTTP Proxy Server"""
    
    def __init__(self, bind_ip, bind_port, web_server_ip, web_server_port):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.web_server_ip = web_server_ip
        self.web_server_port = web_server_port
        self.socket = None
        self.cache = HTTPCache()
        self.running = True
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "gateway_errors": 0,
            "timeout_errors": 0
        }
        self.stats_lock = threading.Lock()
    
    def forward_to_web_server(self, request_data, client_ip):
        """Teruskan permintaan HTTP ke server web dan dapatkan respons."""
        try:
            # Connect to web server
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.settimeout(SOCKET_TIMEOUT)
            
            start_time = time.time()
            server_socket.connect((self.web_server_ip, self.web_server_port))
            
            # Kirim permintaan ke server web
            server_socket.sendall(request_data.encode('utf-8'))
            
            # nerima response dari web server
            response = b""
            while True:
                try:
                    chunk = server_socket.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    break
            
            server_socket.close()
            
            processing_time = (time.time() - start_time) * 1000
            return response.decode('utf-8', errors='ignore'), processing_time
            
        except socket.timeout:
            logger.warning(f"[{client_ip}] Timeout connecting to web server {self.web_server_ip}:{self.web_server_port}")
            with self.stats_lock:
                self.stats["timeout_errors"] += 1
            return "HTTP/1.1 504 Gateway Timeout\r\nContent-Type: text/plain\r\n\r\n504 Gateway Timeout", 0
        except ConnectionRefusedError:
            logger.error(f"[{client_ip}] Connection refused by web server {self.web_server_ip}:{self.web_server_port}")
            with self.stats_lock:
                self.stats["gateway_errors"] += 1
            return "HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\n\r\n502 Bad Gateway", 0
        except Exception as e:
            logger.error(f"[{client_ip}] Error forwarding to web server: {e}")
            with self.stats_lock:
                self.stats["gateway_errors"] += 1
            return "HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\n\r\n502 Bad Gateway", 0
    
    def extract_path(self, request_data):
        """Ekstrak jalur permintaan dari permintaan HTTP"""
        try:
            lines = request_data.split('\r\n')
            request_line = lines[0]
            parts = request_line.split()
            if len(parts) >= 2:
                return parts[1]
        except Exception as e:
            logger.error(f"Error extracting path: {e}")
        return None
    
    def handle_client(self, client_socket, client_address):
        """Tangani satu koneksi klien"""
        start_time = time.time()
        client_ip = client_address[0]
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        cache_status = "MISS"
        data_size = 0
        
        try:
            client_socket.settimeout(SOCKET_TIMEOUT)
            
            # Terima permintaan HTTP
            request_data = client_socket.recv(4096).decode('utf-8')
            
            if not request_data:
                logger.warning(f"[{client_ip}] Empty request received")
                return
            
            data_size = len(request_data.encode('utf-8'))
            path = self.extract_path(request_data)
            
            with self.stats_lock:
                self.stats["total_requests"] += 1
            
            # meriksa cache
            cached_response = self.cache.get(path)
            if cached_response:
                response = cached_response
                cache_status = "HIT"
                with self.stats_lock:
                    self.stats["cache_hits"] += 1
            else:
                # nerusin ke server web
                response, forward_time = self.forward_to_web_server(request_data, client_ip)
                cache_status = "MISS"
                with self.stats_lock:
                    self.stats["cache_misses"] += 1
                
                # buat simpan respons yang berhasil dalam cache.
                self.cache.set(path, response)
            
            # Kirim respons ke klien
            client_socket.sendall(response.encode('utf-8', errors='ignore'))
            
            # ngitung metrik
            processing_time = (time.time() - start_time) * 1000
            response_size = len(response.encode('utf-8', errors='ignore'))
            
            # transaksi log
            logger.info(
                f"TCP | Client: {client_ip} | Destination: {self.web_server_ip}:{self.web_server_port} | "
                f"Cache: {cache_status} | Data Size: {data_size} bytes | "
                f"Response Size: {response_size} bytes | Processing Time: {processing_time:.2f} ms"
            )
            
        except socket.timeout:
            logger.warning(f"[{client_ip}] Socket timeout")
        except Exception as e:
            logger.error(f"[{client_ip}] Error handling client: {e}")
        finally:
            client_socket.close()
    
    def start(self):
        """mulai proxy http"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.socket.bind((self.bind_ip, self.bind_port))
            self.socket.listen(5)
            logger.info(
                f"HTTP Proxy listening on {self.bind_ip}:{self.bind_port} "
                f"(forwarding to {self.web_server_ip}:{self.web_server_port})"
            )
            
            while self.running:
                try:
                    client_socket, client_address = self.socket.accept()
                    
                    # menangani setiap klien dalam thread baru
                    thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address),
                        daemon=True
                    )
                    thread.start()
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error(f"Error accepting client: {e}")
                    
        except socket.error as e:
            logger.error(f"Socket error: {e}")
        finally:
            self.socket.close()
            logger.info("HTTP Proxy stopped")
    
    def stop(self):
        """nge stop proxy"""
        self.running = False


class UDPQoSProxy:
    """Proxy UDP QoS untuk meneruskan datagram"""
    
    def __init__(self, bind_ip, bind_port, web_server_ip, web_server_port):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.web_server_ip = web_server_ip
        self.web_server_port = web_server_port
        self.socket = None
        self.running = True
        self.stats = {
            "total_packets": 0,
            "forwarded_packets": 0,
            "failed_packets": 0
        }
        self.stats_lock = threading.Lock()
    
    def handle_packet(self, data, client_address):
        """nerusin paket UDP ke server web dan ngirim balasan"""
        client_ip = client_address[0]
        packet_size = len(data)
        start_time = time.time()
        
        try:
            # nerusin ke server web
            forward_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            forward_socket.settimeout(SOCKET_TIMEOUT)
            forward_socket.sendto(data, (self.web_server_ip, self.web_server_port))
            
            # nerima balasan
            response_data, _ = forward_socket.recvfrom(65535)
            forward_socket.close()
            
            # ngirim balasan ke klien
            self.socket.sendto(response_data, client_address)
            
            processing_time = (time.time() - start_time) * 1000
            
            with self.stats_lock:
                self.stats["forwarded_packets"] += 1
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            logger.info(
                f"UDP | Client: {client_ip} | Destination: {self.web_server_ip}:{self.web_server_port} | "
                f"Packet Size: {packet_size} bytes | Timestamp: {timestamp} | "
                f"Processing Time: {processing_time:.2f} ms"
            )
            
        except socket.timeout:
            logger.warning(f"[{client_ip}] UDP timeout forwarding to web server")
            with self.stats_lock:
                self.stats["failed_packets"] += 1
        except Exception as e:
            logger.error(f"[{client_ip}] Error forwarding UDP packet: {e}")
            with self.stats_lock:
                self.stats["failed_packets"] += 1
    
    def start(self):
        """mulai proxy UDP QoS"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.socket.bind((self.bind_ip, self.bind_port))
            self.socket.settimeout(1.0)
            logger.info(
                f"UDP QoS Proxy listening on {self.bind_ip}:{self.bind_port} "
                f"(forwarding to {self.web_server_ip}:{self.web_server_port})"
            )
            
            while self.running:
                try:
                    data, client_address = self.socket.recvfrom(65535)
                    
                    with self.stats_lock:
                        self.stats["total_packets"] += 1
                    
                    # buat nangani paket dalam thread untuk menghindari blocking
                    thread = threading.Thread(
                        target=self.handle_packet,
                        args=(data, client_address),
                        daemon=True
                    )
                    thread.start()
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"Error handling UDP packet: {e}")
                    
        except socket.error as e:
            logger.error(f"UDP Socket error: {e}")
        finally:
            self.socket.close()
            logger.info("UDP QoS Proxy stopped")
    
    def stop(self):
        """Stop the UDP proxy"""
        self.running = False


def print_stats(http_proxy, udp_proxy):
    """Ngeprint statistik proxy"""
    while True:
        time.sleep(30)  # Print stats every 30 seconds
        try:
            logger.info("=" * 70)
            logger.info("PROXY STATISTICS")
            logger.info("=" * 70)
            
            with http_proxy.stats_lock:
                logger.info(f"TCP - Total Requests: {http_proxy.stats['total_requests']}")
                logger.info(f"TCP - Cache Hits: {http_proxy.stats['cache_hits']}")
                logger.info(f"TCP - Cache Misses: {http_proxy.stats['cache_misses']}")
                logger.info(f"TCP - Gateway Errors: {http_proxy.stats['gateway_errors']}")
                logger.info(f"TCP - Timeout Errors: {http_proxy.stats['timeout_errors']}")
            
            with udp_proxy.stats_lock:
                logger.info(f"UDP - Total Packets: {udp_proxy.stats['total_packets']}")
                logger.info(f"UDP - Forwarded: {udp_proxy.stats['forwarded_packets']}")
                logger.info(f"UDP - Failed: {udp_proxy.stats['failed_packets']}")
            
            logger.info(f"Cache Status: {http_proxy.cache.get_stats()}")
            logger.info("=" * 70)
        except Exception as e:
            logger.error(f"Error printing stats: {e}")


def main():
    """main fungsi startup proxy"""
    logger.info("=" * 70)
    logger.info("Proxy Server starting...")
    logger.info(f"Proxy IP (local): 10.60.14.86")
    logger.info(f"Web Server IP: {WEB_SERVER_IP}")
    logger.info("=" * 70)
    
    # inisiasi HTTP Proxy
    http_proxy = HTTPProxy(
        CLIENT_BIND_IP, CLIENT_TCP_PORT,
        WEB_SERVER_IP, WEB_SERVER_TCP_PORT
    )
    
    # inisiasi UDP QoS Proxy
    udp_proxy = UDPQoSProxy(
        CLIENT_BIND_IP, CLIENT_UDP_PORT,
        WEB_SERVER_IP, WEB_SERVER_UDP_PORT
    )
    
    # mulai HTTP proxy dalam thread terpisah
    http_thread = threading.Thread(target=http_proxy.start, daemon=False)
    http_thread.start()
    
    # mulai UDP proxy dalam thread terpisah
    udp_thread = threading.Thread(target=udp_proxy.start, daemon=True)
    udp_thread.start()
    
    # mulai stats printer dalam thread terpisah
    stats_thread = threading.Thread(target=print_stats, args=(http_proxy, udp_proxy), daemon=True)
    stats_thread.start()
    
    try:
        # ngejaga supaya proxy tetep jalan
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down proxy...")
        http_proxy.stop()
        udp_proxy.stop()
        http_thread.join(timeout=5)
        logger.info("Proxy stopped")


if __name__ == "__main__":
    main()
