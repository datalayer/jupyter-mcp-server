# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for issue #470: configurable jupyter-mcp-tools timeout
and no routing poisoning on an empty tools/list.

The `wait_timeout=5` inside `_fetch_jupyter_tools` was hardcoded, which is not
enough on deployments with many JupyterLab commands (44s measured for 585
commands), and a `tools/list` that answered `[]` (503/timeout) wiped
`MCPSSEHandler._jupyter_tool_names`, so later `tools/call` requests stopped
routing to jupyter-mcp-tools. These tests use stand-ins for jupyter-mcp-tools
and the MCP server, so no running Jupyter server is required.

Launch the tests:
```
$ pytest tests/test_jupyter_mcp_tools_timeout.py -v
```
"""

import json
import sys
import types
from types import SimpleNamespace
from unittest import mock

import pytest

from jupyter_mcp_server.config import get_config, reset_config, set_config

BASE_URL = "http://localhost:8888"


@pytest.fixture
def stub_jupyter_mcp_tools(monkeypatch):
    """Replace jupyter_mcp_tools.get_tools with a recorder of its kwargs."""
    calls = []

    async def fake_get_tools(**kwargs):
        calls.append(kwargs)
        return [{"id": "notebook_run-all-cells"}]

    stub = types.ModuleType("jupyter_mcp_tools")
    stub.get_tools = fake_get_tools
    monkeypatch.setitem(sys.modules, "jupyter_mcp_tools", stub)
    return calls


@pytest.fixture
def clean_config():
    reset_config()
    yield
    reset_config()


class TestConfigurableTimeout:
    """The wait applied to jupyter-mcp-tools comes from configuration."""

    def test_timeout_defaults_to_five_seconds(self, clean_config):
        """The default is unchanged: a missing frontend must still fail fast."""
        assert get_config().jupyter_mcp_tools_timeout == 5

    def test_extension_trait_defaults_to_five_seconds(self):
        from jupyter_mcp_server.jupyter_extension.extension import (
            JupyterMCPServerExtensionApp,
        )

        trait = JupyterMCPServerExtensionApp.class_traits()["jupyter_mcp_tools_timeout"]
        assert trait.default_value == 5

    @pytest.mark.asyncio
    async def test_fetch_uses_the_default_timeout(self, clean_config, stub_jupyter_mcp_tools):
        from jupyter_mcp_server.jupyter_extension import handlers

        await handlers._fetch_jupyter_tools(
            base_url=BASE_URL, token="t", query="q", enabled_only=False
        )
        assert stub_jupyter_mcp_tools[0]["wait_timeout"] == 5

    @pytest.mark.asyncio
    async def test_fetch_uses_the_configured_timeout(self, clean_config, stub_jupyter_mcp_tools):
        """set_config (what the extension trait feeds) changes the wait."""
        from jupyter_mcp_server.jupyter_extension import handlers

        set_config(jupyter_mcp_tools_timeout=44)
        await handlers._fetch_jupyter_tools(
            base_url=BASE_URL, token="t", query="q", enabled_only=False
        )
        assert stub_jupyter_mcp_tools[0]["wait_timeout"] == 44


class TestEmptyListKeepsRouting:
    """An empty tools/list answer must not wipe known routing names."""

    @pytest.mark.asyncio
    async def test_empty_tools_list_does_not_wipe_known_routing_names(
        self, clean_config, monkeypatch
    ):
        """Drive the real tools/list branch with an empty jupyter-mcp-tools
        answer and check the routing cache still holds what it knew."""
        from jupyter_mcp_server.jupyter_extension import handlers
        from jupyter_mcp_server.jupyter_extension.handlers import MCPSSEHandler

        set_config(jupyterlab=True, allowed_jupyter_mcp_tools="notebook_run-all-cells")

        # A previous tools/list already learned this tool; tools/call routes on it.
        MCPSSEHandler._jupyter_tool_names = {"notebook_run-all-cells"}
        try:
            fake_mcp = SimpleNamespace(list_tools=mock.AsyncMock(return_value=[]))
            monkeypatch.setattr(
                "jupyter_mcp_server.server.mcp", fake_mcp, raising=False
            )
            monkeypatch.setattr(
                handlers,
                "get_server_context",
                lambda: SimpleNamespace(serverapp=None),
            )
            server_context = SimpleNamespace(
                is_jupyterlab_mode=lambda: True,
            )
            monkeypatch.setattr(
                handlers.ServerContext, "get_instance", classmethod(lambda cls: server_context)
            )
            empty_cache = SimpleNamespace(get_tools=mock.AsyncMock(return_value=[]))
            monkeypatch.setattr(
                "jupyter_mcp_server.tool_cache.get_tool_cache", lambda: empty_cache
            )

            handler = MCPSSEHandler.__new__(MCPSSEHandler)
            # `settings` is a read-only property off `application` on a real
            # handler, so stub the application instead of assigning it.
            handler.application = SimpleNamespace(settings={"port": 8888, "token": None})
            handler.request = SimpleNamespace(
                body=json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
                ).encode()
            )
            written = {}
            handler.write = lambda chunk: written.setdefault("body", chunk)
            handler.finish = lambda: None
            handler.set_header = lambda *args: None

            await handler.post()

            assert MCPSSEHandler._jupyter_tool_names == {"notebook_run-all-cells"}, (
                "an empty tools/list answer wiped the routing names, "
                "so tools/call stops reaching jupyter-mcp-tools"
            )
            response = json.loads(written["body"])
            assert response["result"] == {"tools": []}
        finally:
            MCPSSEHandler._jupyter_tool_names = set()

    @pytest.mark.asyncio
    async def test_non_empty_tools_list_still_refreshes_routing_names(
        self, clean_config, monkeypatch
    ):
        """Regression guard: a real answer must still replace the cache."""
        from jupyter_mcp_server.jupyter_extension import handlers
        from jupyter_mcp_server.jupyter_extension.handlers import MCPSSEHandler

        set_config(jupyterlab=True, allowed_jupyter_mcp_tools="notebook_run-all-cells")

        MCPSSEHandler._jupyter_tool_names = {"stale-tool"}
        try:
            fake_mcp = SimpleNamespace(list_tools=mock.AsyncMock(return_value=[]))
            monkeypatch.setattr(
                "jupyter_mcp_server.server.mcp", fake_mcp, raising=False
            )
            monkeypatch.setattr(
                handlers,
                "get_server_context",
                lambda: SimpleNamespace(serverapp=None),
            )
            server_context = SimpleNamespace(
                is_jupyterlab_mode=lambda: True,
            )
            monkeypatch.setattr(
                handlers.ServerContext, "get_instance", classmethod(lambda cls: server_context)
            )
            fresh = [{"id": "notebook_run-all-cells"}]
            full_cache = SimpleNamespace(get_tools=mock.AsyncMock(return_value=fresh))
            monkeypatch.setattr(
                "jupyter_mcp_server.tool_cache.get_tool_cache", lambda: full_cache
            )

            handler = MCPSSEHandler.__new__(MCPSSEHandler)
            # `settings` is a read-only property off `application` on a real
            # handler, so stub the application instead of assigning it.
            handler.application = SimpleNamespace(settings={"port": 8888, "token": None})
            handler.request = SimpleNamespace(
                body=json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
                ).encode()
            )
            written = {}
            handler.write = lambda chunk: written.setdefault("body", chunk)
            handler.finish = lambda: None
            handler.set_header = lambda *args: None

            await handler.post()

            assert MCPSSEHandler._jupyter_tool_names == {"notebook_run-all-cells"}
        finally:
            MCPSSEHandler._jupyter_tool_names = set()
