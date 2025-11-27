# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tool Cache Module

Provides caching for expensive jupyter-mcp-tools queries to improve performance.
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from jupyter_mcp_server.log import logger


@dataclass
class CacheEntry:
    """Represents a cached entry with timestamp and data."""
    data: List[Dict[str, Any]]
    timestamp: float
    
    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if the cache entry has expired."""
        return time.time() - self.timestamp > ttl_seconds


class ToolCache:
    """
    Cache for jupyter-mcp-tools data with TTL support.
    
    This cache stores the complete tool data to avoid expensive get_tools() calls.
    """
    
    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        """
        Initialize the tool cache.
        
        Args:
            default_ttl: Default time-to-live in seconds for cache entries
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
    
    def _make_cache_key(self, base_url: str, query: str) -> str:
        """Create a cache key from the request parameters."""
        # Use a simplified key based on base_url and query
        # Don't include token for security reasons
        return f"{base_url}:{query}"
    
    async def get_tools(
        self,
        base_url: str,
        token: str,
        query: str,
        enabled_only: bool = False,
        ttl_seconds: Optional[int] = None,
        fetch_func: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Get tools from cache or fetch them if not cached/expired.
        
        Args:
            base_url: Jupyter server base URL
            token: Authentication token
            query: Search query for tools
            enabled_only: Whether to return only enabled tools
            ttl_seconds: Custom TTL for this request (overrides default)
            fetch_func: Function to call if cache miss (should be jupyter_mcp_tools.get_tools)
            
        Returns:
            List of tool dictionaries
        """
        cache_key = self._make_cache_key(base_url, query)
        ttl = ttl_seconds or self._default_ttl
        
        async with self._lock:
            # Check if we have a valid cache entry
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                if not entry.is_expired(ttl):
                    logger.debug(f"Cache HIT for {cache_key} (age: {time.time() - entry.timestamp:.1f}s)")
                    return entry.data
                else:
                    logger.debug(f"Cache EXPIRED for {cache_key} (age: {time.time() - entry.timestamp:.1f}s)")
                    del self._cache[cache_key]
            else:
                logger.debug(f"Cache MISS for {cache_key}")
        
        # Cache miss or expired - fetch fresh data
        if fetch_func is None:
            logger.warning("No fetch function provided for cache miss - returning empty list")
            return []
        
        try:
            logger.info(f"Fetching fresh tools from jupyter-mcp-tools (query: '{query}')")
            fresh_data = await fetch_func(
                base_url=base_url,
                token=token,
                query=query,
                enabled_only=enabled_only
            )
            
            # Store in cache
            async with self._lock:
                self._cache[cache_key] = CacheEntry(
                    data=fresh_data,
                    timestamp=time.time()
                )
            
            logger.info(f"Cached {len(fresh_data)} tools for key {cache_key}")
            return fresh_data
            
        except Exception as e:
            logger.error(f"Failed to fetch tools from jupyter-mcp-tools: {e}")
            # Return empty list on error to prevent cascading failures
            return []
    
    async def invalidate(self, base_url: str, query: str = None):
        """
        Invalidate cache entries.
        
        Args:
            base_url: Base URL to invalidate entries for
            query: Specific query to invalidate (if None, invalidates all for base_url)
        """
        async with self._lock:
            if query is None:
                # Invalidate all entries for this base_url
                keys_to_remove = [
                    key for key in self._cache.keys() 
                    if key.startswith(f"{base_url}:")
                ]
                for key in keys_to_remove:
                    del self._cache[key]
                logger.info(f"Invalidated {len(keys_to_remove)} cache entries for {base_url}")
            else:
                # Invalidate specific entry
                cache_key = self._make_cache_key(base_url, query)
                if cache_key in self._cache:
                    del self._cache[cache_key]
                    logger.info(f"Invalidated cache entry for {cache_key}")
    
    async def clear(self):
        """Clear all cache entries."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared {count} cache entries")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "total_entries": len(self._cache),
            "entries": [
                {
                    "key": key,
                    "age_seconds": time.time() - entry.timestamp,
                    "expired": entry.is_expired(self._default_ttl),
                    "data_count": len(entry.data)
                }
                for key, entry in self._cache.items()
            ]
        }


# Global cache instance
_global_tool_cache = None


def get_tool_cache() -> ToolCache:
    """Get the global tool cache instance."""
    global _global_tool_cache
    if _global_tool_cache is None:
        _global_tool_cache = ToolCache(default_ttl=300)  # 5 minutes
    return _global_tool_cache