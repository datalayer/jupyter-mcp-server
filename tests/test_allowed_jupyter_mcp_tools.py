# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for the ALLOWED_JUPYTER_MCP_TOOLS allowlist.

jupyter-mcp-tools filters its response only when the query is non-empty: its request
handler guards the filter with `if query:`. Joining an empty allowlist into a query
string therefore asks it for every registered JupyterLab command. These tests replace
jupyter_mcp_tools with a stand-in that reproduces that behaviour, so no running
JupyterLab frontend is required.
"""

import sys
import types

import pytest

BASE_URL = "http://localhost:8888"

ALL_TOOLS = [
    {"id": "notebook_run-all-cells", "label": "Run All Cells", "isEnabled": True},
    {"id": "notebook_get-selected-cell", "label": "Get Selected Cell", "isEnabled": True},
    {"id": "notebook_delete-cell", "label": "Delete Cell", "isEnabled": True},
    {"id": "filebrowser_delete", "label": "Delete File", "isEnabled": True},
    {"id": "terminal_open", "label": "Open Terminal", "isEnabled": True},
]

ALL_TOOL_IDS = {tool["id"] for tool in ALL_TOOLS}


class RecordingTools:
    """Stand-in for jupyter_mcp_tools.get_tools that records every query it receives
    and filters the way jupyter-mcp-tools does: no filter at all for an empty query."""

    def __init__(self):
        self.queries = []

    async def __call__(self, query=None, **kwargs):
        self.queries.append(query)
        if not query:
            return list(ALL_TOOLS)
        terms = [term.strip().lower() for term in query.split(",")]
        return [
            tool
            for tool in ALL_TOOLS
            if any(
                term in tool["id"].lower() or term in tool["label"].lower() for term in terms
            )
        ]


@pytest.fixture
def registered_tools(monkeypatch):
    """Drive get_registered_tools() in JUPYTER_SERVER mode against a stand-in
    jupyter_mcp_tools, and yield (call the allowlist, get back the JupyterLab tool ids)."""
    from jupyter_mcp_server import tool_cache
    from jupyter_mcp_server.config import reset_config, set_config
    from jupyter_mcp_server.server import get_registered_tools, server_context
    from jupyter_mcp_server.tools import ServerMode

    fetch = RecordingTools()
    stub = types.ModuleType("jupyter_mcp_tools")
    stub.get_tools = fetch
    monkeypatch.setitem(sys.modules, "jupyter_mcp_tools", stub)
    monkeypatch.setattr(tool_cache, "_global_tool_cache", None, raising=False)
    monkeypatch.setattr(server_context.__class__, "_mode", ServerMode.JUPYTER_SERVER)
    monkeypatch.setattr(server_context.__class__, "_initialized", True)
    # No `serverapp` is injected onto server_context here. The real extension context is
    # left to report the serverapp it actually holds (none, outside a running server),
    # which selects the documented fallback to the configured sandbox URL.

    async def run(allowed):
        reset_config()
        config = set_config(jupyterlab=True, code_sandbox_url=BASE_URL)
        # The extension assigns this attribute directly, which is how an empty allowlist
        # reaches the config at all: set_config() drops "" as an alias for None.
        config.allowed_jupyter_mcp_tools = allowed
        tools = await get_registered_tools()
        return {tool["name"] for tool in tools} & ALL_TOOL_IDS

    yield run, fetch
    reset_config()


@pytest.mark.asyncio
async def test_empty_allowlist_registers_no_jupyterlab_tools(registered_tools):
    """An empty allowlist enables no JupyterLab command, so none may be registered and
    jupyter-mcp-tools must not be asked for a filter it would ignore."""
    run, fetch = registered_tools

    assert await run("") == set()
    assert fetch.queries == []


@pytest.mark.asyncio
async def test_whitespace_only_allowlist_registers_no_jupyterlab_tools(registered_tools):
    """get_allowed_jupyter_mcp_tools() drops blank entries, so ' , ' is also empty."""
    run, fetch = registered_tools

    assert await run(" , ") == set()
    assert fetch.queries == []


@pytest.mark.asyncio
async def test_configured_allowlist_still_registers_its_tools(registered_tools):
    """The allowlist keeps working: a configured command is queried for and registered."""
    run, fetch = registered_tools

    assert await run("notebook_run-all-cells") == {"notebook_run-all-cells"}
    assert fetch.queries == ["notebook_run-all-cells"]


@pytest.mark.asyncio
async def test_serverapp_is_read_from_the_extension_context(registered_tools):
    """The connection details come from the extension context, which is the object that
    carries the ServerApp.

    get_registered_tools() used to read `serverapp` off the module-level
    `jupyter_mcp_server.server_context.ServerContext`, which defines no such attribute.
    The resulting AttributeError was caught by the enclosing `except Exception`, so the
    jupyter-mcp-tools fetch was never attempted and the allowlist silently registered
    nothing.
    """
    run, fetch = registered_tools

    registered = await run("notebook_run-all-cells,terminal_open")

    # The fetch was attempted at all, which the AttributeError used to prevent.
    assert fetch.queries == ["notebook_run-all-cells,terminal_open"]
    assert registered == {"notebook_run-all-cells", "terminal_open"}
