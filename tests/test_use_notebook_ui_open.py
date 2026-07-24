# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for the use_notebook JupyterLab UI opening gate.

These tests drive UseNotebookTool with an in-memory stand-in for the
jupyter-mcp-tools client, so no running JupyterLab is required. They cover the
server-side decision to dispatch `docmanager_open`, not the browser behaviour
that dispatch causes.
"""

import pytest

from jupyter_mcp_server.config import get_config, reset_config
from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool


class FakeFile:
    """Minimal stand-in for a jupyter-server-client directory entry."""

    def __init__(self, name):
        self.name = name


class FakeContents:
    def __init__(self, names):
        self._names = names

    def list_directory(self, path):
        return [FakeFile(name) for name in self._names]


class FakeServerClient:
    """Minimal stand-in for JupyterServerClient covering the surface
    use_notebook touches on the switch path: status and a directory listing."""

    def __init__(self, names):
        self.contents = FakeContents(names)

    def get_status(self):
        return {"version": "2.0.0"}


class FakeMCPToolsClient:
    """Stand-in for jupyter_mcp_tools' MCPToolsClient that records the tools it
    is asked to execute instead of calling a live JupyterLab."""

    calls = []

    def __init__(self, base_url=None, token=None):
        self.base_url = base_url
        self.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute_tool(self, tool_id, parameters=None):
        type(self).calls.append((tool_id, parameters))
        return {"success": True}


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Each test gets a clean config, context flag, and call recorder."""
    reset_config()
    FakeMCPToolsClient.calls = []
    monkeypatch.setattr("jupyter_mcp_tools.client.MCPToolsClient", FakeMCPToolsClient)
    yield
    reset_config()


def _manager_with_two_notebooks():
    """A manager holding two notebooks, with 'nb1' active, so that using 'nb2'
    takes the switch path that activates a different notebook."""
    nm = NotebookManager()
    for name in ("nb1", "nb2"):
        nm.add_notebook(
            name,
            {"id": f"kernel-{name}"},
            server_url="http://localhost:8888",
            token="token",
            path=f"work/{name}.ipynb",
        )
    nm.set_current_notebook("nb1")
    return nm


async def _switch_to_nb2(notebook_manager):
    """Switch the active notebook from nb1 to nb2 over the MCP_SERVER path."""
    get_server_context().update(context_type="MCP_SERVER", jupyterlab=True)
    return await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=FakeServerClient(["nb1.ipynb", "nb2.ipynb"]),
        notebook_manager=notebook_manager,
        notebook_name="nb2",
        notebook_path="work/nb2.ipynb",
        use_mode="connect",
        runtime_url="http://localhost:8888",
        runtime_token="token",
    )


@pytest.mark.asyncio
async def test_switching_notebook_does_not_open_ui_by_default():
    """Switching notebooks must not steal the JupyterLab tab focus unless the
    user asked for it, so no docmanager_open is dispatched by default."""
    nm = _manager_with_two_notebooks()

    await _switch_to_nb2(nm)

    assert nm.get_current_notebook() == "nb2"
    assert FakeMCPToolsClient.calls == []


@pytest.mark.asyncio
async def test_switching_notebook_opens_ui_when_opted_in():
    """With open_notebook_in_ui set, the previous behaviour is preserved: the
    notebook is opened in the JupyterLab UI."""
    get_config().open_notebook_in_ui = True
    nm = _manager_with_two_notebooks()

    await _switch_to_nb2(nm)

    assert FakeMCPToolsClient.calls == [("docmanager_open", {"path": "work/nb2.ipynb"})]


@pytest.mark.asyncio
async def test_ui_open_stays_off_when_jupyterlab_mode_disabled():
    """The opt-in does not re-enable UI opening outside JupyterLab mode."""
    get_config().open_notebook_in_ui = True
    nm = _manager_with_two_notebooks()

    get_server_context().update(context_type="MCP_SERVER", jupyterlab=False)
    await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=FakeServerClient(["nb1.ipynb", "nb2.ipynb"]),
        notebook_manager=nm,
        notebook_name="nb2",
        notebook_path="work/nb2.ipynb",
        use_mode="connect",
        runtime_url="http://localhost:8888",
        runtime_token="token",
    )

    assert FakeMCPToolsClient.calls == []


def test_open_notebook_in_ui_defaults_to_off():
    """The opt-in is off by default, leaving jupyter-mcp-tools loading (which
    the separate `jupyterlab` flag gates) untouched."""
    assert get_config().open_notebook_in_ui is False
