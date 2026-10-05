# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""get_registered_tools() must work out the server mode itself.

It used to read `ServerContext._mode`, which stays None until something calls
`initialize()`. On a freshly started Jupyter extension, the REST
`GET /mcp/tools/list` was therefore answered as if in MCP_SERVER mode and
listed `connect_to_jupyter`, until a JSON-RPC request initialized the context.
"""

from types import SimpleNamespace

import pytest

from jupyter_mcp_server.jupyter_extension import context as extension_context
from jupyter_mcp_server.server import get_registered_tools
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.tools import ServerMode


@pytest.fixture
def fresh_extension_context(monkeypatch):
    """An uninitialized ServerContext inside a local-document Jupyter extension."""
    local_extension = SimpleNamespace(
        is_local_document=lambda: True,
        get_contents_manager=lambda: object(),
        get_kernel_manager=lambda: object(),
        is_jupyterlab_mode=lambda: False,
    )
    monkeypatch.setattr(extension_context, "get_server_context", lambda: local_extension)
    ServerContext.reset()
    yield
    ServerContext.reset()


@pytest.mark.asyncio
async def test_a_fresh_extension_lists_tools_in_jupyter_server_mode(fresh_extension_context):
    assert ServerContext.get_instance()._mode is None

    names = {tool["name"] for tool in await get_registered_tools()}

    assert ServerContext.get_instance()._mode == ServerMode.JUPYTER_SERVER
    assert "connect_to_jupyter" not in names
    assert "list_notebooks" in names
