#!/usr/bin/env python3


import socket
import threading
import time
import sys
import csv
import statistics
from datetime import datetime
from collections import defaultdict
import argparse


PROXY_IP = "10.60.14.86"            
PROXY_TCP_PORT = 8080               
PROXY_UDP_PORT = 9090                
REQUEST_PATH = "/"                   
SOCKET_TIMEOUT = 10                  


# Global logging lock
log_lock = threading.Lock()


def log_message(message):
    """Thread-safe logging"""
    with log_lock:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}")


class HTTPClient:
    """TCP HTTP Client"""
    
    def __init__(self, proxy_ip, proxy_port, request_path="/"):
        self.proxy_ip = proxy_ip
        self.proxy_port = proxy_port
        self.request_path = request_path
    
    def send_request(self, save_to_file=None):
        """Send HTTP GET request to proxy and display response"""
        try:
            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            
            log_message(f"[TCP] Connecting to proxy {self.proxy_ip}:{self.proxy_port}...")
            sock.connect((self.proxy_ip, self.proxy_port))
            log_message(f"[TCP] Connected to proxy")
            
            # Create HTTP request
            request = (
                f"GET {self.request_path} HTTP/1.1\r\n"
                f"Host: {self.proxy_ip}:{self.proxy_port}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            
            start_time = time.time()
            
            # Send request
            log_message(f"[TCP] Sending HTTP GET {self.request_path}...")
            sock.sendall(request.encode('utf-8'))
            
            # Receive response
            response = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    break
            
            sock.close()
            
            processing_time = (time.time() - start_time) * 1000
            response_str = response.decode('utf-8', errors='ignore')
            response_size = len(response)
            
            # Parse response headers and body
            parts = response_str.split('\r\n\r\n', 1)
            headers = parts[0] if len(parts) > 0 else ""
            body = parts[1] if len(parts) > 1 else ""
            
            # Extract status code
            status_line = headers.split('\r\n')[0] if headers else ""
            
            log_message(f"[TCP] Response received in {processing_time:.2f} ms ({response_size} bytes)")
            log_message(f"[TCP] Status: {status_line}")
            log_message(f"[TCP] Response Headers:\n{headers}")
            log_message(f"[TCP] Response Body:\n{body}")
            
            # Save to file if requested
            if save_to_file:
                try:
                    with open(save_to_file, 'w', encoding='utf-8') as f:
                        f.write(body)
                    log_message(f"[TCP] Response body saved to {save_to_file}")
                except Exception as e:
                    log_message(f"[TCP] Error saving to file: {e}")
            
            return True
            
        except socket.timeout:
            log_message(f"[TCP] Socket timeout after {SOCKET_TIMEOUT} seconds")
        except ConnectionRefusedError:
            log_message(f"[TCP] Connection refused by proxy {self.proxy_ip}:{self.proxy_port}")
        except Exception as e:
            log_message(f"[TCP] Error: {e}")
        
        return False


class QoSMetrics:
    """Calculate QoS metrics"""
    
    def __init__(self):
        self.latencies = []
        self.received_packets = 0
        self.sent_packets = 0
        self.start_time = None
        self.end_time = None
    
    def add_latency(self, latency):
        """Add a latency measurement"""
        self.latencies.append(latency)
        self.received_packets += 1
    
    def calculate_stats(self):
        """Calculate QoS statistics"""
        if not self.latencies:
            return None
        
        stats = {
            "sent_packets": self.sent_packets,
            "received_packets": self.received_packets,
            "packet_loss": ((self.sent_packets - self.received_packets) / self.sent_packets * 100) if self.sent_packets > 0 else 0,
            "min_latency": min(self.latencies),
            "max_latency": max(self.latencies),
            "avg_latency": statistics.mean(self.latencies),
            "jitter": statistics.stdev(self.latencies) if len(self.latencies) > 1 else 0,
            "throughput": (self.received_packets / (self.end_time - self.start_time)) if (self.end_time - self.start_time) > 0 else 0,
        }
        
        return stats
    
    def print_results(self):
        """Print QoS results"""
        stats = self.calculate_stats()
        
        if not stats:
            log_message("[QoS] No packets received")
            return
        
        log_message("=" * 70)
        log_message("[QoS] STATISTICS SUMMARY")
        log_message("=" * 70)
        log_message(f"Packets Sent: {stats['sent_packets']}")
        log_message(f"Packets Received: {stats['received_packets']}")
        log_message(f"Packet Loss: {stats['packet_loss']:.2f}%")
        log_message(f"Min Latency: {stats['min_latency']:.3f} ms")
        log_message(f"Max Latency: {stats['max_latency']:.3f} ms")
        log_message(f"Average Latency: {stats['avg_latency']:.3f} ms")
        log_message(f"Jitter (Std Dev): {stats['jitter']:.3f} ms")
        log_message(f"Throughput: {stats['throughput']:.2f} packets/sec")
        log_message("=" * 70)
    
    def export_to_csv(self, filename):
        """Export results to CSV file"""
        try:
            stats = self.calculate_stats()
            if not stats:
                log_message("[QoS] No data to export")
                return False
            
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Metric", "Value"])
                writer.writerow(["Packets Sent", stats['sent_packets']])
                writer.writerow(["Packets Received", stats['received_packets']])
                writer.writerow(["Packet Loss %", f"{stats['packet_loss']:.2f}"])
                writer.writerow(["Min Latency (ms)", f"{stats['min_latency']:.3f}"])
                writer.writerow(["Max Latency (ms)", f"{stats['max_latency']:.3f}"])
                writer.writerow(["Avg Latency (ms)", f"{stats['avg_latency']:.3f}"])
                writer.writerow(["Jitter (ms)", f"{stats['jitter']:.3f}"])
                writer.writerow(["Throughput (pkt/s)", f"{stats['throughput']:.2f}"])
                
                # Write individual latencies
                writer.writerow([])
                writer.writerow(["Packet", "Latency (ms)"])
                for i, latency in enumerate(self.latencies, 1):
                    writer.writerow([i, f"{latency:.3f}"])
            
            log_message(f"[QoS] Results exported to {filename}")
            return True
            
        except Exception as e:
            log_message(f"[QoS] Error exporting to CSV: {e}")
            return False


class UDPQoSClient:
    """UDP QoS Testing Client"""
    
    def __init__(self, proxy_ip, proxy_port, packet_size=64, packet_count=10, interval=0.1):
        self.proxy_ip = proxy_ip
        self.proxy_port = proxy_port
        self.packet_size = packet_size
        self.packet_count = packet_count
        self.interval = interval
        self.metrics = QoSMetrics()
    
    def send_qos_test(self):
        """Send QoS test packets"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(SOCKET_TIMEOUT)
            
            log_message(f"[UDP] Starting QoS test:")
            log_message(f"[UDP] - Proxy: {self.proxy_ip}:{self.proxy_port}")
            log_message(f"[UDP] - Packet size: {self.packet_size} bytes")
            log_message(f"[UDP] - Packet count: {self.packet_count}")
            log_message(f"[UDP] - Interval: {self.interval} sec")
            
            # Create payload
            payload = b"X" * self.packet_size
            
            self.metrics.start_time = time.time()
            self.metrics.sent_packets = self.packet_count
            
            # Send packets
            for i in range(self.packet_count):
                try:
                    send_time = time.time()
                    sock.sendto(payload, (self.proxy_ip, self.proxy_port))
                    
                    # Try to receive echo
                    try:
                        response, _ = sock.recvfrom(self.packet_size + 1024)
                        recv_time = time.time()
                        latency = (recv_time - send_time) * 1000  # Convert to ms
                        self.metrics.add_latency(latency)
                        log_message(f"[UDP] Packet {i+1}/{self.packet_count}: {latency:.3f} ms")
                    except socket.timeout:
                        log_message(f"[UDP] Packet {i+1}/{self.packet_count}: TIMEOUT")
                    
                    # Wait before sending next packet
                    if i < self.packet_count - 1:
                        time.sleep(self.interval)
                
                except Exception as e:
                    log_message(f"[UDP] Error sending packet {i+1}: {e}")
            
            self.metrics.end_time = time.time()
            sock.close()
            
            # Print results
            self.metrics.print_results()
            
            return True
            
        except Exception as e:
            log_message(f"[UDP] Error: {e}")
            return False


class MultiClientSimulator:
    """Simulate multiple concurrent clients"""
    
    def __init__(self, num_clients, mode="http"):
        self.num_clients = num_clients
        self.mode = mode
        self.results = []
        self.lock = threading.Lock()
    
    def run_http_client(self, client_id):
        """Run a single HTTP client"""
        log_message(f"[Multi-Client] Client {client_id} starting HTTP test...")
        
        client = HTTPClient(PROXY_IP, PROXY_TCP_PORT, REQUEST_PATH)
        success = client.send_request()
        
        with self.lock:
            self.results.append({
                "client_id": client_id,
                "mode": "HTTP",
                "success": success
            })
        
        log_message(f"[Multi-Client] Client {client_id} finished")
    
    def run_qos_client(self, client_id):
        """Run a single QoS client"""
        log_message(f"[Multi-Client] Client {client_id} starting UDP QoS test...")
        
        qos_client = UDPQoSClient(
            PROXY_IP, PROXY_UDP_PORT,
            packet_size=64,
            packet_count=10,
            interval=0.1
        )
        success = qos_client.send_qos_test()
        
        with self.lock:
            self.results.append({
                "client_id": client_id,
                "mode": "UDP",
                "success": success
            })
        
        log_message(f"[Multi-Client] Client {client_id} finished")
    
    def simulate(self):
        """Simulate multiple concurrent clients"""
        threads = []
        
        for i in range(1, self.num_clients + 1):
            if self.mode == "http":
                thread = threading.Thread(
                    target=self.run_http_client,
                    args=(i,),
                    daemon=False
                )
            else:  # UDP
                thread = threading.Thread(
                    target=self.run_qos_client,
                    args=(i,),
                    daemon=False
                )
            
            threads.append(thread)
            thread.start()
            
            # Stagger client starts
            time.sleep(0.5)
        
        # Wait for all clients to finish
        for thread in threads:
            thread.join()
        
        # Print summary
        log_message("=" * 70)
        log_message("[Multi-Client] SUMMARY")
        log_message("=" * 70)
        
        successful = sum(1 for r in self.results if r["success"])
        log_message(f"Total Clients: {self.num_clients}")
        log_message(f"Successful: {successful}")
        log_message(f"Failed: {self.num_clients - successful}")
        log_message("=" * 70)


def main():
    """Main client function"""
    parser = argparse.ArgumentParser(description="Computer Networks Project Client")
    parser.add_argument(
        "--mode",
        choices=["http", "qos", "multi"],
        default="http",
        help="Client mode: http (default), qos, or multi-client"
    )
    parser.add_argument(
        "--path",
        default="/",
        help="HTTP request path (default: /)"
    )
    parser.add_argument(
        "--save",
        help="Save HTTP response to file"
    )
    parser.add_argument(
        "--pkt-size",
        type=int,
        default=64,
        help="QoS packet size in bytes (default: 64)"
    )
    parser.add_argument(
        "--pkt-count",
        type=int,
        default=10,
        help="QoS packet count (default: 10)"
    )
    parser.add_argument(
        "--pkt-interval",
        type=float,
        default=0.1,
        help="QoS packet interval in seconds (default: 0.1)"
    )
    parser.add_argument(
        "--num-clients",
        type=int,
        default=2,
        help="Number of concurrent clients for multi-client mode (default: 2, max: 5)"
    )
    parser.add_argument(
        "--export-csv",
        help="Export QoS results to CSV file"
    )
    
    args = parser.parse_args()
    
    log_message("=" * 70)
    log_message(f"Client starting in {args.mode.upper()} mode")
    log_message(f"Proxy: {PROXY_IP}:{PROXY_TCP_PORT}")
    log_message("=" * 70)
    
    if args.mode == "http":
        # HTTP mode
        client = HTTPClient(PROXY_IP, PROXY_TCP_PORT, args.path)
        client.send_request(save_to_file=args.save)
        
    elif args.mode == "qos":
        # QoS mode
        qos_client = UDPQoSClient(
            PROXY_IP, PROXY_UDP_PORT,
            packet_size=args.pkt_size,
            packet_count=args.pkt_count,
            interval=args.pkt_interval
        )
        qos_client.send_qos_test()
        
        # Export to CSV if requested
        if args.export_csv:
            qos_client.metrics.export_to_csv(args.export_csv)
        
    elif args.mode == "multi":
        # Multi-client simulation
        num_clients = min(args.num_clients, 5)  # Max 5 clients
        
        # Alternate between HTTP and UDP for multi-client demo
        simulator = MultiClientSimulator(num_clients // 2, mode="http")
        simulator.simulate()
        
        time.sleep(2)  # Brief pause between tests
        
        simulator_qos = MultiClientSimulator(num_clients // 2, mode="udp")
        simulator_qos.simulate()
    
    log_message("=" * 70)
    log_message("Client finished")
    log_message("=" * 70)


if __name__ == "__main__":
    main()
