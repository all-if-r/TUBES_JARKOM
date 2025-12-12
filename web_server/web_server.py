#!/usr/bin/env python3


import socket
import threading
import logging
import os
import time
from datetime import datetime
from pathlib import Path


TCP_IP = "0.0.0.0"  # Listen on all network interfaces
TCP_PORT = 8000     # HTTP port - change if conflicts occur
UDP_IP = "0.0.0.0"  # Listen on all network interfaces
UDP_PORT = 9000     # UDP echo port - change if conflicts occur
HTML_FILE_PATH = "../test-tubes-jarkom.html"  # Relative path to HTML file
SOCKET_TIMEOUT = 30  # Socket timeout in seconds (5-30 seconds recommended)
# ============================================================================

# Concurrency mode: Set to False for single-threaded, True for multi-threaded
MULTI_THREADED = True

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler('web_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class WebServer:
    """TCP HTTP Web Server component"""
    
    def __init__(self, ip, port, html_file_path):
        self.ip = ip
        self.port = port
        self.html_file_path = html_file_path
        self.socket = None
        self.html_content = None
        self.running = True
        
    def load_html_file(self):
        """Load HTML file into memory"""
        try:
            with open(self.html_file_path, 'r', encoding='utf-8') as f:
                self.html_content = f.read()
            logger.info(f"HTML file loaded successfully ({len(self.html_content)} bytes)")
            return True
        except FileNotFoundError:
            logger.error(f"HTML file not found at: {self.html_file_path}")
            self.html_content = "<html><body><h1>404 - File Not Found</h1></body></html>"
            return False
        except Exception as e:
            logger.error(f"Error loading HTML file: {e}")
            self.html_content = "<html><body><h1>500 - Server Error</h1></body></html>"
            return False
    
    def parse_http_request(self, request_data):
        """Parse HTTP GET request and extract the path"""
        try:
            lines = request_data.split('\r\n')
            request_line = lines[0]
            parts = request_line.split()
            
            if len(parts) < 2:
                return None
            
            method = parts[0]
            path = parts[1]
            
            if method != "GET":
                return None
            
            return path
        except Exception as e:
            logger.error(f"Error parsing HTTP request: {e}")
            return None
    
    def generate_http_response(self, status_code, content):
        """Generate HTTP response with proper headers"""
        status_messages = {
            200: "OK",
            404: "Not Found",
            500: "Internal Server Error"
        }
        
        status_msg = status_messages.get(status_code, "Unknown")
        content_length = len(content.encode('utf-8'))
        
        response = (
            f"HTTP/1.1 {status_code} {status_msg}\r\n"
            f"Content-Type: text/html\r\n"
            f"Content-Length: {content_length}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{content}"
        )
        
        return response
    
    def handle_client(self, client_socket, client_address):
        """Handle a single client connection"""
        start_time = time.time()
        client_ip = client_address[0]
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        try:
            client_socket.settimeout(SOCKET_TIMEOUT)
            
            # Receive HTTP request
            request_data = client_socket.recv(4096).decode('utf-8')
            
            if not request_data:
                logger.warning(f"[{client_ip}] Empty request received")
                return
            
            # Parse request path
            path = self.parse_http_request(request_data)
            
            if path is None:
                response = self.generate_http_response(400, "<html><body><h1>400 - Bad Request</h1></body></html>")
                resource = "INVALID"
                status_code = 400
            elif path in ["/", "/index.html"]:
                # Return HTML file
                response = self.generate_http_response(200, self.html_content)
                resource = path
                status_code = 200
            else:
                # Path not found
                response = self.generate_http_response(404, "<html><body><h1>404 - Not Found</h1></body></html>")
                resource = path
                status_code = 404
            
            # Send response
            client_socket.sendall(response.encode('utf-8'))
            
            # Calculate metrics
            processing_time = (time.time() - start_time) * 1000  # Convert to ms
            response_size = len(response.encode('utf-8'))
            
            # Log transaction
            logger.info(
                f"TCP | Client: {client_ip} | Time: {request_time} | "
                f"Resource: {resource} | Status: {status_code} | "
                f"Response Size: {response_size} bytes | Processing Time: {processing_time:.2f} ms"
            )
            
        except socket.timeout:
            logger.warning(f"[{client_ip}] Socket timeout after {SOCKET_TIMEOUT} seconds")
        except Exception as e:
            logger.error(f"[{client_ip}] Error handling client: {e}")
        finally:
            client_socket.close()
    
    def start(self):
        """Start the TCP server"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.socket.bind((self.ip, self.port))
            self.socket.listen(5)
            logger.info(f"TCP Server listening on {self.ip}:{self.port}")
            
            while self.running:
                try:
                    client_socket, client_address = self.socket.accept()
                    
                    if MULTI_THREADED:
                        # Multi-threaded: handle each client in a new thread
                        thread = threading.Thread(
                            target=self.handle_client,
                            args=(client_socket, client_address),
                            daemon=True
                        )
                        thread.start()
                    else:
                        # Single-threaded: handle client sequentially
                        self.handle_client(client_socket, client_address)
                        
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error(f"Error accepting client: {e}")
                    
        except socket.error as e:
            logger.error(f"Socket error: {e}")
        finally:
            self.socket.close()
            logger.info("TCP Server stopped")
    
    def stop(self):
        """Stop the server"""
        self.running = False


class UDPEchoServer:
    """UDP Echo Server for QoS testing"""
    
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.socket = None
        self.running = True
    
    def start(self):
        """Start the UDP echo server"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.socket.bind((self.ip, self.port))
            self.socket.settimeout(1.0)  # Non-blocking timeout for graceful shutdown
            logger.info(f"UDP Echo Server listening on {self.ip}:{self.port}")
            
            while self.running:
                try:
                    data, client_address = self.socket.recvfrom(65535)
                    client_ip = client_address[0]
                    packet_size = len(data)
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    
                    # Echo the data back
                    self.socket.sendto(data, client_address)
                    
                    # Log packet
                    logger.info(
                        f"UDP | Source IP: {client_ip} | Packet Size: {packet_size} bytes | "
                        f"Timestamp: {timestamp}"
                    )
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"Error in UDP handler: {e}")
                    
        except socket.error as e:
            logger.error(f"UDP Socket error: {e}")
        finally:
            self.socket.close()
            logger.info("UDP Echo Server stopped")
    
    def stop(self):
        """Stop the UDP server"""
        self.running = False


def main():
    """Main server startup function"""
    logger.info("=" * 70)
    logger.info("Web Server starting...")
    logger.info(f"Mode: {'Multi-threaded' if MULTI_THREADED else 'Single-threaded'}")
    logger.info("=" * 70)
    
    # Initialize TCP Web Server
    web_server = WebServer(TCP_IP, TCP_PORT, HTML_FILE_PATH)
    web_server.load_html_file()
    
    # Initialize UDP Echo Server
    udp_server = UDPEchoServer(UDP_IP, UDP_PORT)
    
    # Start TCP server in main thread
    tcp_thread = threading.Thread(target=web_server.start, daemon=False)
    tcp_thread.start()
    
    # Start UDP server in separate thread
    udp_thread = threading.Thread(target=udp_server.start, daemon=True)
    udp_thread.start()
    
    try:
        # Keep the server running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down servers...")
        web_server.stop()
        udp_server.stop()
        tcp_thread.join(timeout=5)
        logger.info("Servers stopped")


if __name__ == "__main__":
    main()
