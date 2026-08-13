# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Which tools an agent is offered, and what they mean.

An agent works from the tool list. Offer it a tool that always fails and it
keeps trying, then invents an explanation — a hosted session offering to
connect to a Jupyter on the user's laptop is what that looks like. So the list
itself is the thing under test here.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from jupyter_mcp_spaces import SpacesExtension
from jupyter_mcp_spaces.extension import JUPYTER_ONLY_TOOLS


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    """The server's configuration, as the extension reads it."""

    def _set(provider="datalayer"):
        from jupyter_mcp_server.config import set_config

        set_config(document_provider=provider, document_url="https://spacer.test")

    _set()
    yield _set
    from jupyter_mcp_server.config import reset_config

    reset_config()


def _server_with_upstream_tools() -> FastMCP:
    """A server carrying the tools the open source project registers."""
    mcp = FastMCP("test")

    @mcp.tool()
    def list_files() -> str:
        """Upstream: lists a Jupyter directory."""
        return "files"

    @mcp.tool()
    def list_kernels() -> str:
        """Upstream: lists Jupyter kernels."""
        return "kernels"

    @mcp.tool()
    def connect_to_jupyter() -> str:
        """Upstream: connects to a Jupyter server."""
        return "connected"

    @mcp.tool()
    def list_notebooks() -> str:
        """Upstream: notebooks bound in this session."""
        return "No managed notebooks."

    return mcp


async def _names(mcp: FastMCP) -> list[str]:
    return [tool.name for tool in await mcp.list_tools()]


class TestTheToolList:
    @pytest.mark.asyncio
    async def test_the_jupyter_only_tools_are_hidden(self):
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        names = await _names(mcp)
        for hidden in JUPYTER_ONLY_TOOLS:
            assert hidden not in names

    @pytest.mark.asyncio
    async def test_list_notebooks_is_replaced_not_shadowed(self):
        """The failure this guards against is silent.

        FastMCP warns "Tool already exists" and *keeps the original*, so a
        replacement registered on a live name does nothing at all — the agent
        still gets the session registry, still reports no notebooks, and
        nothing in the logs says why.
        """
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        tool = mcp._tool_manager._tools["list_notebooks"]
        assert "Datalayer spaces" in tool.description
        assert "bound in this session" not in tool.description

    @pytest.mark.asyncio
    async def test_the_spaces_tools_are_added(self):
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        names = await _names(mcp)
        assert "list_spaces" in names
        assert "list_notebooks" in names
        assert "find_notebook" in names

    @pytest.mark.asyncio
    async def test_a_jupyter_server_is_left_untouched(self, _config):
        """Pointed at a Jupyter, its own tools are the right ones.

        Replacing them there would break the ordinary single-user case this
        project exists for.
        """
        _config(provider="jupyter")
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        names = await _names(mcp)
        for kept in JUPYTER_ONLY_TOOLS:
            assert kept in names
        assert "list_spaces" not in names

    @pytest.mark.asyncio
    async def test_registering_twice_is_harmless(self):
        # Removing a tool that is already gone raises in FastMCP, so a second
        # pass must not take the server down.
        mcp = _server_with_upstream_tools()
        extension = SpacesExtension()
        extension.register_tools(mcp)
        extension.register_tools(mcp)
        assert "list_spaces" in await _names(mcp)

    @pytest.mark.asyncio
    async def test_a_server_without_those_tools_is_fine(self):
        # An upstream release may rename one. That must not stop startup.
        mcp = FastMCP("bare")
        SpacesExtension().register_tools(mcp)
        assert "list_notebooks" in await _names(mcp)
