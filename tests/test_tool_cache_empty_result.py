# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for ToolCache's handling of an empty tool list.

jupyter-mcp-tools returns [] rather than raising when the JupyterLab extension has
not registered its tools yet (HTTP 503), when the request times out, or on a
connection error. Caching that empty list would pin a transient failure for the
whole TTL. These tests use a fake fetch function, so no running Jupyter server and
no jupyter-mcp-tools installation are required.
"""

import pytest

from jupyter_mcp_server.tool_cache import ToolCache

BASE_URL = "http://localhost:8888"
TOKEN = "test-token"
QUERY = "notebook_run-cell"

TOOLS = [
    {"id": "notebook_run-cell", "label": "Run Cell", "enabled": True},
    {"id": "notebook_insert-cell", "label": "Insert Cell", "enabled": True},
]


class RecordingFetch:
    """A jupyter_mcp_tools.get_tools stand-in that returns a scripted result per call
    and counts how many times the backend was actually asked."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls = 0

    async def __call__(self, **kwargs):
        self.calls += 1
        return self._results.pop(0) if self._results else []


@pytest.mark.asyncio
async def test_empty_result_is_not_cached_and_next_call_refetches():
    """A transient failure returns [], and the next call must reach the backend
    again rather than serving the empty list from cache."""
    cache = ToolCache(default_ttl=300)
    fetch = RecordingFetch([], TOOLS)

    first = await cache.get_tools(
        base_url=BASE_URL, token=TOKEN, query=QUERY, fetch_func=fetch
    )
    assert first == []
    assert cache.get_cache_stats()["total_entries"] == 0

    second = await cache.get_tools(
        base_url=BASE_URL, token=TOKEN, query=QUERY, fetch_func=fetch
    )
    assert second == TOOLS
    assert fetch.calls == 2


@pytest.mark.asyncio
async def test_non_empty_result_is_still_cached():
    """The caching behaviour itself is unchanged: a real answer is stored and the
    second call is served without asking the backend again."""
    cache = ToolCache(default_ttl=300)
    fetch = RecordingFetch(TOOLS, TOOLS)

    first = await cache.get_tools(
        base_url=BASE_URL, token=TOKEN, query=QUERY, fetch_func=fetch
    )
    second = await cache.get_tools(
        base_url=BASE_URL, token=TOKEN, query=QUERY, fetch_func=fetch
    )

    assert first == TOOLS
    assert second == TOOLS
    assert fetch.calls == 1
    assert cache.get_cache_stats()["total_entries"] == 1
