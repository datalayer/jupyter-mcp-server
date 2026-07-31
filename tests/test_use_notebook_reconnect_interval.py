# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""use_notebook's MCP_SERVER kernel-creation path must forward the configured
reconnect_interval/execution_timeout to create_jupyter_sandbox_client, the same
way its sibling call sites (utils.create_kernel, execute_code_tool) already do.
"""

from unittest.mock import patch

import pytest

import jupyter_mcp_server.tools.use_notebook_tool as use_notebook_tool
from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool


class _FakeContents:
    @staticmethod
    def create_notebook(path, content=None):
        return None

    @staticmethod
    def list_directory(path):
        return []


class _FakeKernels:
    @staticmethod
    def list_kernels():
        return []


class FakeServerClient:
    """Stand-in for JupyterServerClient: no live server needed, only the
    surface use_notebook touches before it reaches kernel creation."""

    contents = _FakeContents
    kernels = _FakeKernels

    def get_status(self):
        return {}


class FakeKernel:
    id = "kernel-1"


@pytest.fixture
def configured_reconnect():
    reset_config()
    set_config(reconnect_interval=5, execution_timeout=300)
    yield
    reset_config()


@pytest.mark.asyncio
async def test_use_notebook_mcp_server_forwards_reconnect_interval(configured_reconnect):
    """A configured --reconnect-interval must reach create_jupyter_sandbox_client
    on the use_notebook MCP_SERVER path, not be silently dropped."""
    with patch.object(
        use_notebook_tool, "create_jupyter_sandbox_client", return_value=FakeKernel()
    ) as mock_create:
        await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            server_client=FakeServerClient(),
            notebook_manager=NotebookManager(),
            notebook_name="nb",
            notebook_path="nb.ipynb",
            use_mode="create",
            code_sandbox_url="http://localhost:8888",
            code_sandbox_token="secret",
        )

    assert mock_create.call_count == 1
    kwargs = mock_create.call_args.kwargs
    assert kwargs["reconnect_interval"] == 5
    assert kwargs["timeout"] == 300


@pytest.mark.asyncio
async def test_use_notebook_mcp_server_defaults_reconnect_interval_to_zero(configured_reconnect):
    """No --reconnect-interval configured means 0 (disabled), matching the
    sibling call sites' `getattr(config, "reconnect_interval", 0) or 0`."""
    reset_config()

    with patch.object(
        use_notebook_tool, "create_jupyter_sandbox_client", return_value=FakeKernel()
    ) as mock_create:
        await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            server_client=FakeServerClient(),
            notebook_manager=NotebookManager(),
            notebook_name="nb2",
            notebook_path="nb2.ipynb",
            use_mode="create",
            code_sandbox_url="http://localhost:8888",
            code_sandbox_token="secret",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["reconnect_interval"] == 0
