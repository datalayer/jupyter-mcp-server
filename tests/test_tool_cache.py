# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Tests for ToolCache.

The cache exists to absorb an expensive and routinely-failing call: the
handlers themselves note that a failed fetch is "normal if JupyterLab frontend
is not loaded". These tests cover the two paths where it does not.

Launch the tests:
```
$ pytest tests/test_tool_cache.py -v
```
"""

import asyncio

import pytest

from jupyter_mcp_server.tool_cache import ToolCache

BASE_URL = "http://localhost:8888"
TOOLS = [{"id": "tool-a"}, {"id": "tool-b"}]


class TestServeStaleOnFetchFailure:
    """An expired entry must not be dropped until a refetch succeeds."""

    @pytest.mark.asyncio
    async def test_failed_refresh_keeps_serving_the_cached_tools(self):
        calls = {"n": 0}

        async def flaky_fetch(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return TOOLS
            raise RuntimeError("frontend not loaded")

        cache = ToolCache(default_ttl=1)

        first = await cache.get_tools(
            base_url=BASE_URL, token="t", query="q", fetch_func=flaky_fetch
        )
        assert len(first) == 2

        await asyncio.sleep(1.1)  # let the entry expire

        # The refresh fails. The previously cached tools are still the best
        # answer available, and dropping them makes every tool disappear.
        after = await cache.get_tools(
            base_url=BASE_URL, token="t", query="q", fetch_func=flaky_fetch
        )
        assert len(after) == 2, "a failed refresh must not empty the tool list"

    @pytest.mark.asyncio
    async def test_failed_refresh_does_not_discard_the_entry(self):
        calls = {"n": 0}

        async def flaky_fetch(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return TOOLS
            raise RuntimeError("frontend not loaded")

        cache = ToolCache(default_ttl=1)
        await cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=flaky_fetch)

        await asyncio.sleep(1.1)
        await cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=flaky_fetch)

        assert cache.get_cache_stats()["total_entries"] == 1, (
            "the entry was discarded before the refetch was known to work"
        )

    @pytest.mark.asyncio
    async def test_successful_refresh_still_replaces_the_entry(self):
        """Regression guard: a working refresh must return the new data."""
        versions = [[{"id": "old"}], [{"id": "new"}]]

        async def fetch(**kwargs):
            return versions.pop(0)

        cache = ToolCache(default_ttl=1)
        first = await cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=fetch)
        assert first == [{"id": "old"}]

        await asyncio.sleep(1.1)
        second = await cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=fetch)
        assert second == [{"id": "new"}]

    @pytest.mark.asyncio
    async def test_first_ever_fetch_failure_still_returns_empty(self):
        """With nothing cached there is nothing to fall back to."""

        async def always_fails(**kwargs):
            raise RuntimeError("frontend not loaded")

        cache = ToolCache(default_ttl=300)
        result = await cache.get_tools(
            base_url=BASE_URL, token="t", query="q", fetch_func=always_fails
        )
        assert result == []


class TestConcurrentMissCoalescing:
    """Concurrent callers on a cold cache should share one fetch."""

    @pytest.mark.asyncio
    async def test_concurrent_cold_callers_share_one_fetch(self):
        calls = {"n": 0}

        async def slow_fetch(**kwargs):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return TOOLS

        cache = ToolCache(default_ttl=300)

        results = await asyncio.gather(
            *[
                cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=slow_fetch)
                for _ in range(10)
            ]
        )

        assert all(len(r) == 2 for r in results)
        assert calls["n"] == 1, (
            f"the cache exists to avoid repeated expensive calls, but made {calls['n']}"
        )

    @pytest.mark.asyncio
    async def test_distinct_queries_are_not_serialised_into_one_fetch(self):
        """Regression guard: coalescing must be per key, not global."""
        calls = {"n": 0}

        async def fetch(**kwargs):
            calls["n"] += 1
            await asyncio.sleep(0.01)
            return TOOLS

        cache = ToolCache(default_ttl=300)
        await asyncio.gather(
            cache.get_tools(base_url=BASE_URL, token="t", query="a", fetch_func=fetch),
            cache.get_tools(base_url=BASE_URL, token="t", query="b", fetch_func=fetch),
        )
        assert calls["n"] == 2


class TestInflightIsolation:
    """Joining a shared fetch must not change what this caller asked for."""

    @pytest.mark.asyncio
    async def test_a_different_fetcher_is_not_served_by_the_in_flight_one(self):
        """The two call sites pass fetchers with different timeouts.

        handlers.py wraps get_tools with wait_timeout=5 ("if frontend isn't
        loaded, don't wait long"); server.py passes the bare get_tools, whose
        default is 30. Every other key component is identical between them, so
        joining by query alone hands the short-timeout caller the long fetch.
        """
        used = []
        started = asyncio.Event()

        async def slow_fetcher(**kwargs):
            used.append("slow")
            started.set()
            await asyncio.sleep(0.20)
            return TOOLS

        async def fast_fetcher(**kwargs):
            used.append("fast")
            await asyncio.sleep(0.01)
            return TOOLS

        cache = ToolCache(default_ttl=300)

        creator = asyncio.create_task(
            cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=slow_fetcher)
        )
        await started.wait()

        await cache.get_tools(
            base_url=BASE_URL, token="t", query="q", ttl_seconds=180, fetch_func=fast_fetcher
        )
        await creator

        assert "fast" in used, "the joining caller's fetch_func was silently replaced"

    @pytest.mark.asyncio
    async def test_same_fetcher_still_coalesces(self):
        """Regression guard: the fetcher is part of the key, not the whole key."""
        calls = {"n": 0}

        async def fetch(**kwargs):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return TOOLS

        cache = ToolCache(default_ttl=300)
        await asyncio.gather(
            *[
                cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=fetch)
                for _ in range(5)
            ]
        )
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_one_caller_cancelling_does_not_abort_the_shared_fetch(self):
        """A client disconnecting must not empty the tool list for everyone else.

        `await task` on a shared task propagates the awaiting caller's
        cancellation into it, and CancelledError is a BaseException, so the
        other callers do not even reach the stale-serving fallback below.
        """
        started = asyncio.Event()

        async def slow_fetch(**kwargs):
            started.set()
            await asyncio.sleep(0.20)
            return TOOLS

        cache = ToolCache(default_ttl=300)

        first = asyncio.create_task(
            cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=slow_fetch)
        )
        await started.wait()
        second = asyncio.create_task(
            cache.get_tools(base_url=BASE_URL, token="t", query="q", fetch_func=slow_fetch)
        )
        await asyncio.sleep(0.02)  # let the second caller join the in-flight task

        first.cancel()

        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == TOOLS, "an unrelated caller's cancellation emptied the tool list"
        assert cache.get_cache_stats()["total_entries"] == 1


class TestCacheKey:
    """enabled_only changes the result, so it has to be part of the key."""

    @pytest.mark.asyncio
    async def test_enabled_only_is_not_shared_across_entries(self):
        async def fetch(**kwargs):
            if kwargs.get("enabled_only"):
                return [{"id": "enabled-only"}]
            return TOOLS

        cache = ToolCache(default_ttl=300)

        unfiltered = await cache.get_tools(
            base_url=BASE_URL, token="t", query="q", enabled_only=False, fetch_func=fetch
        )
        filtered = await cache.get_tools(
            base_url=BASE_URL, token="t", query="q", enabled_only=True, fetch_func=fetch
        )

        assert len(unfiltered) == 2
        assert filtered == [{"id": "enabled-only"}], (
            "an enabled_only request was served the unfiltered entry"
        )
