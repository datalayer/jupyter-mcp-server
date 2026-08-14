# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tool Cache Module

Provides caching for expensive jupyter-mcp-tools queries to improve performance.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from jupyter_mcp_server.log import logger


@dataclass
class CacheEntry:
    """Represents a cached entry with timestamp and data."""

    data: list[dict[str, Any]]
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
        self._cache: dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        # In-flight fetches, keyed the same way as _cache, so concurrent callers
        # that miss on the same key share one call instead of each making their own.
        self._inflight: dict[str, asyncio.Task] = {}

    def _make_cache_key(self, base_url: str, query: str, enabled_only: bool = False) -> str:
        """Create a cache key from the request parameters."""
        # Use a simplified key based on base_url, query and enabled_only.
        # enabled_only changes which tools come back, so entries for the two
        # values must not be shared.
        # Don't include token for security reasons
        return f"{base_url}:{query}:{enabled_only}"

    async def _fetch_and_store(
        self,
        cache_key: str,
        fetch_func: Any,
        base_url: str,
        token: str,
        query: str,
        enabled_only: bool,
    ) -> list[dict[str, Any]]:
        """Fetch fresh data and store it. Only replaces the entry on success."""
        try:
            logger.info(f"Fetching fresh tools from jupyter-mcp-tools (query: '{query}')")
            fresh_data = await fetch_func(
                base_url=base_url, token=token, query=query, enabled_only=enabled_only
            )
            # jupyter-mcp-tools returns [] rather than raising when the JupyterLab
            # extension has not registered its tools yet (HTTP 503), on a timeout, or
            # on a connection error, so an empty result is transient here. Leaving the
            # previous entry in place also means an expired one is still available to
            # serve, for the same reason the except branch below falls back to it.
            if not fresh_data:
                logger.debug(f"Not caching empty tool list for key {cache_key}")
                return fresh_data

            async with self._lock:
                self._cache[cache_key] = CacheEntry(data=fresh_data, timestamp=time.time())
            logger.info(f"Cached {len(fresh_data)} tools for key {cache_key}")
            return fresh_data
        finally:
            async with self._lock:
                self._inflight.pop(cache_key, None)

    async def get_tools(
        self,
        base_url: str,
        token: str,
        query: str,
        enabled_only: bool = False,
        ttl_seconds: int | None = None,
        fetch_func: Any | None = None,
    ) -> list[dict[str, Any]]:
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
        cache_key = self._make_cache_key(base_url, query, enabled_only)
        ttl = ttl_seconds or self._default_ttl

        async with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None and not entry.is_expired(ttl):
                logger.debug(
                    f"Cache HIT for {cache_key} (age: {time.time() - entry.timestamp:.1f}s)"
                )
                return entry.data

            if entry is None:
                logger.debug(f"Cache MISS for {cache_key}")
            else:
                logger.debug(
                    f"Cache EXPIRED for {cache_key} (age: {time.time() - entry.timestamp:.1f}s)"
                )

            if fetch_func is None:
                logger.warning("No fetch function provided for cache miss")
                # An expired entry still beats nothing when we cannot refresh.
                return entry.data if entry is not None else []

            # Join an in-flight fetch for this key rather than starting another.
            task = self._inflight.get(cache_key)
            if task is None:
                task = asyncio.create_task(
                    self._fetch_and_store(
                        cache_key, fetch_func, base_url, token, query, enabled_only
                    )
                )
                self._inflight[cache_key] = task

        try:
            return await task
        except Exception as e:
            logger.error(f"Failed to fetch tools from jupyter-mcp-tools: {e}")
            # Serve the stale entry rather than dropping every tool because one
            # refresh failed. A failed fetch is expected when the JupyterLab
            # frontend is not loaded, and it should not empty the tool list.
            async with self._lock:
                stale = self._cache.get(cache_key)
            if stale is not None:
                logger.warning(
                    f"Serving stale tools for {cache_key} "
                    f"(age: {time.time() - stale.timestamp:.1f}s) after a failed refresh"
                )
                return stale.data
            # Nothing cached yet, so there is nothing better to return.
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
                    key for key in self._cache.keys() if key.startswith(f"{base_url}:")
                ]
                for key in keys_to_remove:
                    del self._cache[key]
                logger.info(f"Invalidated {len(keys_to_remove)} cache entries for {base_url}")
            else:
                # Invalidate specific entry
                prefix = f"{base_url}:{query}:"
                keys_to_remove = [key for key in self._cache if key.startswith(prefix)]
                for key in keys_to_remove:
                    del self._cache[key]
                if keys_to_remove:
                    logger.info(f"Invalidated cache entry for {base_url}:{query}")

    async def clear(self):
        """Clear all cache entries."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared {count} cache entries")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "total_entries": len(self._cache),
            "entries": [
                {
                    "key": key,
                    "age_seconds": time.time() - entry.timestamp,
                    "expired": entry.is_expired(self._default_ttl),
                    "data_count": len(entry.data),
                }
                for key, entry in self._cache.items()
            ],
        }


# Global cache instance
_global_tool_cache = None


def get_tool_cache() -> ToolCache:
    """Get the global tool cache instance."""
    global _global_tool_cache
    if _global_tool_cache is None:
        _global_tool_cache = ToolCache(default_ttl=300)  # 5 minutes
    return _global_tool_cache
