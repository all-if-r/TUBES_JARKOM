#!/usr/bin/env python3


import socket
import threading
import logging
import time
from datetime import datetime
from urllib.parse import urlparse
from collections import defaultdict
import json


CLIENT_BIND_IP = "0.0.0.0"           # Listen on all interfaces for clients
CLIENT_TCP_PORT = 8080               # Port for client HTTP requests
CLIENT_UDP_PORT = 9090               # Port for client UDP packets
WEB_SERVER_IP = "10.60.14.89"        # *** CRITICAL: Change if web server IP changes ***
WEB_SERVER_TCP_PORT = 8000           # Web server HTTP port
WEB_SERVER_UDP_PORT = 9000           # Web server UDP echo port
SOCKET_TIMEOUT = 8                   # Socket timeout in seconds (5-10 seconds recommended)


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
    """In-memory HTTP response cache with HTTP 200 OK filtering"""
    
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()
    
    def get(self, path):
        """Get response from cache (returns None if not found or expired)"""
        with self.lock:
            if path in self.cache:
                return self.cache[path]
        return None
    
    def set(self, path, response):
        """Cache a response if it's HTTP 200 OK"""
        try:
            # Extract status code from response
            if response.startswith("HTTP/1.1 200"):
                with self.lock:
                    self.cache[path] = response
                return True
        except Exception as e:
            logger.error(f"Error caching response: {e}")
        return False
    
    def clear(self):
        """Clear all cache"""
        with self.lock:
            self.cache.clear()
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            return {"cached_paths": len(self.cache), "paths": list(self.cache.keys())}


class HTTPProxy:
    """TCP HTTP Proxy Server component"""
    
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
        """Forward HTTP request to web server and get response"""
        try:
            # Connect to web server
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.settimeout(SOCKET_TIMEOUT)
            
            start_time = time.time()
            server_socket.connect((self.web_server_ip, self.web_server_port))
            
            # Send request to web server
            server_socket.sendall(request_data.encode('utf-8'))
            
            # Receive response
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
        """Extract request path from HTTP request"""
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
        """Handle a single client connection"""
        start_time = time.time()
        client_ip = client_address[0]
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        cache_status = "MISS"
        data_size = 0
        
        try:
            client_socket.settimeout(SOCKET_TIMEOUT)
            
            # Receive HTTP request
            request_data = client_socket.recv(4096).decode('utf-8')
            
            if not request_data:
                logger.warning(f"[{client_ip}] Empty request received")
                return
            
            data_size = len(request_data.encode('utf-8'))
            path = self.extract_path(request_data)
            
            with self.stats_lock:
                self.stats["total_requests"] += 1
            
            # Check cache
            cached_response = self.cache.get(path)
            if cached_response:
                response = cached_response
                cache_status = "HIT"
                with self.stats_lock:
                    self.stats["cache_hits"] += 1
            else:
                # Forward to web server
                response, forward_time = self.forward_to_web_server(request_data, client_ip)
                cache_status = "MISS"
                with self.stats_lock:
                    self.stats["cache_misses"] += 1
                
                # Try to cache successful responses
                self.cache.set(path, response)
            
            # Send response to client
            client_socket.sendall(response.encode('utf-8', errors='ignore'))
            
            # Calculate metrics
            processing_time = (time.time() - start_time) * 1000
            response_size = len(response.encode('utf-8', errors='ignore'))
            
            # Log transaction
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
        """Start the HTTP proxy"""
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
                    
                    # Handle each client in a new thread
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
        """Stop the proxy"""
        self.running = False


class UDPQoSProxy:
    """UDP QoS Proxy for forwarding datagrams"""
    
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
        """Forward a UDP packet to web server and relay response"""
        client_ip = client_address[0]
        packet_size = len(data)
        start_time = time.time()
        
        try:
            # Send to web server
            forward_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            forward_socket.settimeout(SOCKET_TIMEOUT)
            forward_socket.sendto(data, (self.web_server_ip, self.web_server_port))
            
            # Receive response
            response_data, _ = forward_socket.recvfrom(65535)
            forward_socket.close()
            
            # Send back to client
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
        """Start the UDP QoS proxy"""
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
                    
                    # Handle packet in a thread to avoid blocking
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
    """Print proxy statistics"""
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
    """Main proxy startup function"""
    logger.info("=" * 70)
    logger.info("Proxy Server starting...")
    logger.info(f"Proxy IP (local): 10.60.14.86")
    logger.info(f"Web Server IP: {WEB_SERVER_IP}")
    logger.info("=" * 70)
    
    # Initialize HTTP Proxy
    http_proxy = HTTPProxy(
        CLIENT_BIND_IP, CLIENT_TCP_PORT,
        WEB_SERVER_IP, WEB_SERVER_TCP_PORT
    )
    
    # Initialize UDP QoS Proxy
    udp_proxy = UDPQoSProxy(
        CLIENT_BIND_IP, CLIENT_UDP_PORT,
        WEB_SERVER_IP, WEB_SERVER_UDP_PORT
    )
    
    # Start HTTP proxy in separate thread
    http_thread = threading.Thread(target=http_proxy.start, daemon=False)
    http_thread.start()
    
    # Start UDP proxy in separate thread
    udp_thread = threading.Thread(target=udp_proxy.start, daemon=True)
    udp_thread.start()
    
    # Start stats printer in separate thread
    stats_thread = threading.Thread(target=print_stats, args=(http_proxy, udp_proxy), daemon=True)
    stats_thread.start()
    
    try:
        # Keep the proxy running
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
