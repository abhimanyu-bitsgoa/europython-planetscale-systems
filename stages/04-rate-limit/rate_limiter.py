"""
Scalability Lab - Rate Limiter

Decorator-based rate limiting with strategy pattern.
Currently implements Fixed Window algorithm with TODO markers for student exercise.

Note: This rate limiter can be extended with more strategies 
(e.g., sliding window, token bucket, leaky bucket) for different use cases.
"""

import time
from typing import Dict, Tuple, Callable
from functools import wraps
from abc import ABC, abstractmethod
from collections import defaultdict

# ========================
# Rate Limiting Strategies
# ========================

class RateLimiterStrategy(ABC):
    """Abstract base class for rate limiting strategies."""
    
    @abstractmethod
    def is_allowed(self, client_id: str) -> Tuple[bool, dict]:
        """
        Check if a request from this client is allowed.
        
        Returns:
            Tuple of (is_allowed, metadata_dict)
            metadata_dict contains: remaining, limit, reset
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get the name of this strategy."""
        pass

class FixedWindowStrategy(RateLimiterStrategy):
    """
    Fixed Window Rate Limiting Strategy.
    
    How it works:
    - Divides time into fixed windows (e.g., 60 seconds)
    - Counts requests within each window
    - Resets counter when a new window starts
    
    Pros: Simple, memory efficient
    Cons: Burst at window boundaries (can allow 2x limit briefly)
    """
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.buckets: Dict[str, dict] = defaultdict(
            lambda: {"count": 0, "window_start": 0}
        )
    
    def get_name(self) -> str:
        return "fixed_window"
    
    def is_allowed(self, client_id: str) -> Tuple[bool, dict]:
        """Check if a request is allowed under the rate limit (fixed window)."""
        now = time.time()
        bucket = self.buckets[client_id]
        allowed = False

        # TODO [STAGE 04]: the core of a fixed-window limiter — just two steps:
        #   1. If the window has expired (now - bucket["window_start"] >= self.window_seconds),
        #      start a fresh window:  bucket["window_start"] = now;  bucket["count"] = 0
        #   2. If bucket["count"] < self.max_requests, this request fits:
        #      bucket["count"] += 1 and allowed = True   (otherwise leave allowed = False)
        # Replace the line below with those two steps. The metadata after it is done for you.
        raise NotImplementedError("STAGE 04: reset the window if expired, then allow/reject")

        # --- response metadata (done for you) ---
        remaining = max(0, self.max_requests - bucket["count"])
        reset_in = int(bucket["window_start"] + self.window_seconds - now)
        metadata = {
            "remaining": remaining,
            "limit": self.max_requests,
            "reset": reset_in,
            "window_start": bucket["window_start"],
        }
        return allowed, metadata


# Placeholder: Additional strategies can be added here
# Example strategies that could be implemented:
# - SlidingWindowStrategy: More accurate, tracks individual request timestamps
# - TokenBucketStrategy: Allows bursts while maintaining average rate
# - LeakyBucketStrategy: Smooth output rate regardless of input bursts


# ========================
# Rate Limiter Class
# ========================

class RateLimiter:
    """
    Rate Limiter with pluggable strategies.
    
    Usage:
        limiter = RateLimiter(strategy="fixed_window", max_requests=10, window_seconds=60)
        allowed, metadata = limiter.check("client_123")
    """
    
    STRATEGIES = {
        "fixed_window": FixedWindowStrategy,
        # Future strategies can be added here
    }
    
    def __init__(self, strategy: str = "fixed_window", max_requests: int = 10, 
                 window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.strategy_name = strategy
        self.strategy = self._create_strategy(strategy)
    
    def _create_strategy(self, strategy_name: str) -> RateLimiterStrategy:
        """Create a strategy instance by name."""
        if strategy_name not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy_name}. "
                           f"Available: {list(self.STRATEGIES.keys())}")
        return self.STRATEGIES[strategy_name](
            max_requests=self.max_requests,
            window_seconds=self.window_seconds
        )
    
    def check(self, client_id: str) -> Tuple[bool, dict]:
        """
        Check if a request from this client is allowed.
        
        Returns:
            Tuple of (is_allowed, metadata_dict)
        """
        return self.strategy.is_allowed(client_id)
    
    def get_stats(self) -> dict:
        """
        Get current rate limiter statistics.
        
        Returns:
            Dict with strategy name, limits, and per-client bucket info.
        """
        return {
            "strategy": self.strategy_name,
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "clients": dict(self.strategy.buckets) if hasattr(self.strategy, 'buckets') else {}
        }
    

# ========================
# Decorator for Rate Limited Endpoints
# ========================

def rate_limited(limiter: RateLimiter, get_client_id: Callable = None):
    """
    Decorator for rate-limited functions.
    
    Usage:
        limiter = RateLimiter(max_requests=10, window_seconds=60)
        
        @rate_limited(limiter)
        def my_endpoint(request):
            return "Hello!"
    
    The decorator will:
    1. Extract client ID (defaults to "default" if no getter provided)
    2. Check rate limit
    3. Raise RateLimitExceeded if limit exceeded
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get client ID
            if get_client_id:
                client_id = get_client_id(*args, **kwargs)
            else:
                client_id = "default"
            
            # Check rate limit
            allowed, metadata = limiter.check(client_id)
            
            if not allowed:
                raise RateLimitExceeded(
                    f"Rate limit exceeded. Try again in {metadata['reset']} seconds.",
                    metadata=metadata
                )
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator

class RateLimitExceeded(Exception):
    """Exception raised when rate limit is exceeded."""
    
    def __init__(self, message: str, metadata: dict = None):
        super().__init__(message)
        self.metadata = metadata or {}

# ========================
# Convenience Functions
# ========================

def create_rate_limiter(strategy: str = "fixed_window", max_requests: int = 10,
                        window_seconds: int = 60) -> RateLimiter:
    """Create a rate limiter with the specified configuration."""
    return RateLimiter(
        strategy=strategy,
        max_requests=max_requests,
        window_seconds=window_seconds
    )

def get_available_strategies() -> list:
    """Get list of available rate limiting strategies."""
    return list(RateLimiter.STRATEGIES.keys())
