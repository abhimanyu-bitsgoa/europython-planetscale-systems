"""
Scalability Lab - Client

A client that sends requests to nodes with load balancing support.
Demonstrates traffic patterns and load distribution.

Core architecture is consistent across all labs for student familiarity.
"""

import time
import requests
import argparse
import concurrent.futures
from collections import defaultdict

from load_balancer import LoadBalancer, get_available_strategies

# ========================
# Default Configuration
# ========================

DEFAULT_NODES = [
    "http://localhost:5001",
    "http://localhost:5002",
    "http://localhost:5003"
]

# ========================
# Metrics Tracking
# ========================

class ClientMetrics:
    """Track request metrics for visualization."""
    
    def __init__(self):
        self.requests_per_node = defaultdict(int)
        self.latencies_per_node = defaultdict(list)
        self.rate_limited_per_node = defaultdict(int)
        self.errors_per_node = defaultdict(int)
        self.total_requests = 0
        self.total_rate_limited = 0
    
    def record_success(self, node_url: str, latency: float):
        """Record a successful request."""
        self.requests_per_node[node_url] += 1
        self.latencies_per_node[node_url].append(latency)
        self.total_requests += 1
    
    def record_rate_limited(self, node_url: str):
        """Record a rate-limited request (HTTP 429)."""
        self.rate_limited_per_node[node_url] += 1
        self.total_rate_limited += 1
        self.total_requests += 1
    
    def record_error(self, node_url: str):
        """Record a failed request."""
        self.errors_per_node[node_url] += 1
        self.total_requests += 1
    
    def get_avg_latency(self, node_url: str) -> float:
        """Get average latency for a node."""
        latencies = self.latencies_per_node[node_url]
        return sum(latencies) / len(latencies) if latencies else 0.0

metrics = ClientMetrics()

# ========================
# Request Functions
# ========================

def send_request(node_url: str, verbose: bool = False) -> tuple:
    """
    Send a single request to a node.
    
    Returns:
        Tuple of (success, latency_ms, status_code)
    """
    try:
        start_time = time.time()
        resp = requests.post(
            f"{node_url}/data",
            json={"key": "test", "value": "123"},
            timeout=10
        )
        latency = (time.time() - start_time) * 1000
        
        active_reqs = resp.headers.get("X-Active-Requests", "?")
        
        if resp.status_code == 200:
            metrics.record_success(node_url, latency)
            if verbose:
                print(f"[OK]  [{node_url}] 200 | Latency: {latency:.2f}ms | Active: {active_reqs}")
            return True, latency, 200
        
        elif resp.status_code == 429:
            metrics.record_rate_limited(node_url)
            retry_after = resp.headers.get("Retry-After", "?")
            if verbose:
                print(f"[RL]  [{node_url}] 429 RATE LIMITED | Retry-After: {retry_after}s")
            return False, latency, 429
        
        else:
            metrics.record_error(node_url)
            if verbose:
                print(f"[ERR] [{node_url}] {resp.status_code} | Latency: {latency:.2f}ms")
            return False, latency, resp.status_code
    
    except Exception as e:
        metrics.record_error(node_url)
        if verbose:
            print(f"[ERR] Failed to reach {node_url}: {e}")
        return False, 0, 0

# ========================
# Main Client Loop
# ========================

def run_client(nodes: list, concurrency: int, strategy: str, 
               requests_limit: int, rate_delay: float, verbose: bool):
    """
    Run the client with the specified configuration.
    
    Args:
        nodes: List of node URLs
        concurrency: Number of concurrent threads
        strategy: Load balancing strategy (round_robin, adaptive, random)
        requests_limit: Total requests to send (0 = infinite)
        rate_delay: Delay between requests per thread (seconds)
        verbose: Print each request result
    """
    # Create load balancer
    lb = LoadBalancer(nodes=nodes, strategy=strategy)
    
    print(f"Starting Client")
    print(f"   Nodes: {nodes}")
    print(f"   Threads: {concurrency}")
    print(f"   Strategy: {strategy}")
    print(f"   Rate delay: {rate_delay}s")
    if requests_limit:
        print(f"   Request limit: {requests_limit}")
    print()
    
    count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        try:
            while True:
                if requests_limit and count >= requests_limit:
                    break
                
                futures = []
                
                # Schedule a batch of tasks
                for _ in range(concurrency):
                    if requests_limit and count >= requests_limit:
                        break
                    
                    # Get node from load balancer
                    node = lb.get_node()
                    lb.record_request_start(node)
                    
                    futures.append((node, executor.submit(send_request, node, verbose)))
                    count += 1
                
                # Wait for batch to complete and record results
                for node, future in futures:
                    try:
                        success, latency, status_code = future.result()
                        lb.record_request_end(node, latency, success=success)
                    except Exception as e:
                        lb.record_request_end(node, 0, success=False)
                
                # Rate delay between batches
                if rate_delay > 0:
                    time.sleep(rate_delay)
                else:
                    # Small sleep to prevent CPU spin
                    time.sleep(0.01)
        
        except KeyboardInterrupt:
            print("\nClient stopped.")
    
    # Print final stats
    print_stats(nodes)

def print_stats(nodes: list):
    """Print final statistics with P95, median, and global stats."""
    print("\n" + "=" * 60)
    print("FINAL STATISTICS")
    print("=" * 60)
    
    total = metrics.total_requests
    rate_limited = metrics.total_rate_limited
    
    if total == 0:
        print("No requests were made.")
        return
    
    rate_pct = (rate_limited / total * 100) if total > 0 else 0
    print(f"Total Requests: {total}")
    print(f"Rate Limited (429): {rate_limited} ({rate_pct:.1f}%)")
    print()
    
    # Collect all latencies for global stats
    all_latencies = []
    total_success = 0
    total_errors = 0
    
    # Per-node stats
    for node in nodes:
        success = metrics.requests_per_node[node]
        limited = metrics.rate_limited_per_node[node]
        errors = metrics.errors_per_node[node]
        latencies = metrics.latencies_per_node[node]
        
        # Add to global stats
        all_latencies.extend(latencies)
        total_success += success
        total_errors += errors
        
        # Calculate percentiles
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        p95_latency = calculate_percentile(latencies, 95) if latencies else 0.0
        
        print(f"{node}:")
        print(f"  Success: {success}")
        print(f"  Rate Limited: {limited}")
        print(f"  Errors: {errors}")
        print(f"  Avg Latency: {avg_latency:.2f}ms")
        print(f"  P95 Latency: {p95_latency:.2f}ms")
        print()
    
    # Global stats
    print("=" * 60)
    print("GLOBAL SYSTEM STATS")
    print("=" * 60)
    
    if all_latencies:
        global_avg = sum(all_latencies) / len(all_latencies)
        global_p95 = calculate_percentile(all_latencies, 95)
    else:
        global_avg = global_p95 = 0.0
    
    print(f"  Total Success: {total_success}")
    print(f"  Total Rate Limited: {rate_limited}")
    print(f"  Total Errors: {total_errors}")
    print(f"  Global Avg Latency: {global_avg:.2f}ms")
    print(f"  Global P95 Latency: {global_p95:.2f}ms")
    print()

def calculate_percentile(data: list, percentile: float) -> float:
    """Calculate the given percentile of a list of values."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    n = len(sorted_data)
    index = (percentile / 100) * (n - 1)
    
    lower = int(index)
    upper = lower + 1
    
    if upper >= n:
        return sorted_data[-1]
    
    # Linear interpolation
    weight = index - lower
    return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight

# ========================
# Main Entry Point
# ========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scalability Lab - Client")
    parser.add_argument("--concurrent", type=int, default=1,
                        help="Number of concurrent threads")
    parser.add_argument("--target", type=str, default=None,
                        help="Single node URL to target (bypasses load balancing)")
    parser.add_argument("--nodes", type=str, default=None,
                        help="Comma-separated list of node URLs")
    parser.add_argument("--requests", type=int, default=0,
                        help="Total requests to send (0 = infinite)")
    parser.add_argument("--strategy", type=str, default="round_robin",
                        choices=get_available_strategies(),
                        help="Load balancing strategy")
    parser.add_argument("--rate", type=float, default=0,
                        help="Delay between requests in seconds (e.g., --rate 1 for 1 second)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print each request result")
    
    args = parser.parse_args()
    
    # Determine nodes to use
    if args.target:
        nodes = [args.target]
    elif args.nodes:
        nodes = [n.strip() for n in args.nodes.split(",")]
    else:
        nodes = DEFAULT_NODES
    
    try:
        run_client(
            nodes=nodes,
            concurrency=args.concurrent,
            strategy=args.strategy,
            requests_limit=args.requests,
            rate_delay=args.rate,
            verbose=args.verbose
        )
    except KeyboardInterrupt:
        print("\nClient stopped.")
        print_stats(nodes)
