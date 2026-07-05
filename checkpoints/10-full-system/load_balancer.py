"""
Scalability Lab - Load Balancer

Decorator-based load balancing with strategy pattern.
Supports multiple strategies for distributing requests across nodes.

Strategies:
- round_robin: Simple rotating distribution
- adaptive: Prioritizes nodes with faster response times and fewer active requests
"""

import time
import random
from typing import List, Dict, Callable
from functools import wraps
from abc import ABC, abstractmethod

# ========================
# Node Statistics Tracking
# ========================

class NodeStats:
    """Tracks statistics for each node for adaptive load balancing."""
    
    def __init__(self):
        self.stats: Dict[str, dict] = {}
    
    def get_stats(self, node_url: str) -> dict:
        """Get stats for a node, initializing if needed."""
        if node_url not in self.stats:
            self.stats[node_url] = {
                "total_requests": 0,
                "active_requests": 0,
                "total_response_time": 0.0,
                "avg_response_time": 0.0,
                "last_response_time": 0.0,
                "failures": 0
            }
        return self.stats[node_url]
    
    def record_request_start(self, node_url: str):
        """Record that a request to this node has started."""
        stats = self.get_stats(node_url)
        stats["active_requests"] += 1
    
    def record_request_end(self, node_url: str, response_time: float, success: bool = True):
        """Record that a request to this node has completed."""
        stats = self.get_stats(node_url)
        stats["active_requests"] = max(0, stats["active_requests"] - 1)
        stats["total_requests"] += 1
        stats["total_response_time"] += response_time
        stats["last_response_time"] = response_time
        stats["avg_response_time"] = stats["total_response_time"] / stats["total_requests"]
        
        if not success:
            stats["failures"] += 1
    
    def get_score(self, node_url: str) -> float:
        """
        Calculate a score for a node. Lower is better.
        Score = avg_response_time + (active_requests * 100)
        
        This prioritizes nodes with:
        1. Lower average response times
        2. Fewer active requests
        """
        stats = self.get_stats(node_url)
        
        if stats["total_requests"] == 0:
            # Unknown node - give it a neutral score to try it
            return 50.0 + random.random() * 10  # Small randomness to distribute initial requests
        
        return stats["avg_response_time"] + (stats["active_requests"] * 100)

# Global stats tracker
node_stats = NodeStats()

# ========================
# Load Balancing Strategies
# ========================

class LoadBalancerStrategy(ABC):
    """Abstract base class for load balancing strategies."""
    
    @abstractmethod
    def get_node(self, nodes: List[str]) -> str:
        """Select a node from the list of available nodes."""
        pass

class RoundRobinStrategy(LoadBalancerStrategy):
    """
    Round Robin Load Balancing Strategy.
    
    Distributes requests evenly across all nodes in order.
    Simple but doesn't account for node capacity or health.
    """
    
    def __init__(self):
        self.counter = 0
    
    def get_node(self, nodes: List[str]) -> str:
        if not nodes:
            raise ValueError("No nodes available")
        
        node = nodes[self.counter % len(nodes)]
        self.counter += 1
        return node

class AdaptiveStrategy(LoadBalancerStrategy):
    """
    Adaptive Load Balancing Strategy.
    
    Prioritizes nodes with:
    1. Faster response times
    2. Fewer active requests
    
    Great for heterogeneous environments where nodes have different capacities.
    """
    
    def get_node(self, nodes: List[str]) -> str:
        if not nodes:
            raise ValueError("No nodes available")

        # Pick the lowest-score node (score blends latency + active requests; lower is better).
        # We only need the minimum, so this is a single O(n) pass — no full sort.
        return min(nodes, key=node_stats.get_score)

class PowerOfTwoStrategy(LoadBalancerStrategy):
    """
    Power of Two Choices Load Balancing Strategy.
    
    Randomly samples 2 nodes and picks the one with the lower score.
    This prevents the "herd effect" where all clients pile onto
    the same "best" node, while still being adaptive to load.
    
    Used by Netflix, HAProxy, and other high-scale systems.
    """
    
    def get_node(self, nodes: List[str]) -> str:
        if not nodes:
            raise ValueError("No nodes available")
        
        if len(nodes) == 1:
            return nodes[0]
        
        # Sample 2 random nodes
        if len(nodes) == 2:
            candidates = nodes
        else:
            candidates = random.sample(nodes, 2)
        
        # Pick the one with lower score (fewer active requests + lower latency)
        return min(candidates, key=lambda n: node_stats.get_score(n))


class WeightedStrategy(LoadBalancerStrategy):
    """
    Weighted Probability Load Balancing Strategy.
    
    Routes traffic proportionally based on node performance.
    Faster nodes with fewer active requests receive more traffic,
    but not ALL traffic (avoiding the herd effect).
    
    Weight = inverse of score, so lower scores = higher probability.
    """
    
    def get_node(self, nodes: List[str]) -> str:
        if not nodes:
            raise ValueError("No nodes available")
        
        if len(nodes) == 1:
            return nodes[0]
        
        # Calculate scores (lower is better)
        scores = [max(node_stats.get_score(n), 1) for n in nodes]  # avoid div by 0
        
        # Convert to weights (inverse: lower score = higher weight)
        weights = [1000 / score for score in scores]
        
        # Use weighted random choice
        return random.choices(nodes, weights=weights, k=1)[0]


class RandomStrategy(LoadBalancerStrategy):
    """
    Random Load Balancing Strategy.
    
    Randomly selects a node. Simple but provides good distribution
    when node capacities are similar.
    """
    
    def get_node(self, nodes: List[str]) -> str:
        if not nodes:
            raise ValueError("No nodes available")
        
        return random.choice(nodes)

# ========================
# Load Balancer Class
# ========================

class LoadBalancer:
    """
    Load Balancer with pluggable strategies.
    
    Usage:
        lb = LoadBalancer(nodes=["http://localhost:5001", "http://localhost:5002"], 
                          strategy="adaptive")
        node = lb.get_node()
    """
    
    STRATEGIES = {
        "round_robin": RoundRobinStrategy,
        "adaptive": AdaptiveStrategy,
        "power_of_two": PowerOfTwoStrategy,
        "weighted": WeightedStrategy,
        "random": RandomStrategy
    }
    
    def __init__(self, nodes: List[str], strategy: str = "round_robin"):
        self.nodes = nodes
        self.strategy_name = strategy
        self.strategy = self._create_strategy(strategy)
    
    def _create_strategy(self, strategy_name: str) -> LoadBalancerStrategy:
        """Create a strategy instance by name."""
        if strategy_name not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy_name}. "
                           f"Available: {list(self.STRATEGIES.keys())}")
        return self.STRATEGIES[strategy_name]()
    
    def get_node(self) -> str:
        """Get the next node according to the current strategy."""
        return self.strategy.get_node(self.nodes)
    
    def record_request_start(self, node_url: str):
        """Record that a request has started (for adaptive balancing)."""
        node_stats.record_request_start(node_url)
    
    def record_request_end(self, node_url: str, response_time: float, success: bool = True):
        """Record that a request has completed (for adaptive balancing)."""
        node_stats.record_request_end(node_url, response_time, success)
    

# ========================
# Decorator for Load Balanced Requests
# ========================

def load_balanced(lb: LoadBalancer):
    """
    Decorator for making load-balanced requests.
    
    Usage:
        lb = LoadBalancer(nodes, strategy="adaptive")
        
        @load_balanced(lb)
        def make_request(node_url: str):
            # node_url is injected by the decorator
            return requests.get(f"{node_url}/health")
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            node = lb.get_node()
            lb.record_request_start(node)
            
            start_time = time.time()
            try:
                result = func(node, *args, **kwargs)
                response_time = (time.time() - start_time) * 1000
                lb.record_request_end(node, response_time, success=True)
                return result
            except Exception as e:
                response_time = (time.time() - start_time) * 1000
                lb.record_request_end(node, response_time, success=False)
                raise
        
        return wrapper
    return decorator

# ========================
# Convenience Functions
# ========================

def create_load_balancer(nodes: List[str], strategy: str = "round_robin") -> LoadBalancer:
    """Create a load balancer with the specified strategy."""
    return LoadBalancer(nodes=nodes, strategy=strategy)

def get_available_strategies() -> List[str]:
    """Get list of available load balancing strategies."""
    return list(LoadBalancer.STRATEGIES.keys())
