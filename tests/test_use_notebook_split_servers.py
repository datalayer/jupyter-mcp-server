# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Test use_notebook routing for split document and code sandbox servers.

Contents and collaboration requests target the document server, kernel
operations target the code sandbox, and matching URLs preserve the caller's
client.
"""

from types import SimpleNamespace
from unittest.mock import patch

import nbformat
import pytest

from jupyter_mcp_server.config import get_config, reset_config, set_config
from jupyter_mcp_server.jupyter_extension.context import get_server_context
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.tools import use_notebook_tool
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

from .conftest import JUPYTER_TOKEN, _find_free_port, _start_server

DOCUMENT_URL = "http://localhost:9999"
DOCUMENT_TOKEN = "document-token"
SANDBOX_URL = "http://localhost:8888"
SANDBOX_TOKEN = "sandbox-token"


class FakeFile:
    """Minimal jupyter-server-client directory entry."""

    def __init__(self, name):
        self.name = name


class FakeContents:
    """Record Contents API calls instead of hitting a server."""

    def __init__(self, names):
        self._names = names
        self.listed = []
        self.created = []

    def list_directory(self, path):
        self.listed.append(path)
        return [FakeFile(name) for name in self._names]

    def create_notebook(self, path, content=None):
        self.created.append(path)


class FakeServerClient:
    """Minimal JupyterServerClient fake used by the use_notebook tests."""

    def __init__(self, names=()):
        self.contents = FakeContents(names)
        self.http_client = SimpleNamespace(session=SimpleNamespace(headers={}))

    def get_status(self):
        return {"version": "2.0.0"}


class FakeKernel:
    id = "kernel-1"


class FakeMCPToolsClient:
    """Stand-in for jupyter_mcp_tools' MCPToolsClient that records where it was
    pointed and what it was asked to execute."""

    calls = []

    def __init__(self, base_url=None, token=None):
        type(self).calls.append((base_url, token))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute_tool(self, tool_id, parameters=None):
        type(self).calls.append((tool_id, parameters))
        return {"success": True}


@pytest.fixture(autouse=True)
def _reset_config():
    reset_config()
    yield
    reset_config()


async def _execute(sandbox_client, notebook_manager, use_mode="connect", auth_headers=None):
    return await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=sandbox_client,
        notebook_manager=notebook_manager,
        notebook_name="nb",
        notebook_path="work/nb.ipynb",
        use_mode=use_mode,
        code_sandbox_url=SANDBOX_URL,
        code_sandbox_token=SANDBOX_TOKEN,
        auth_headers=auth_headers,
    )


@pytest.mark.asyncio
async def test_split_create_does_not_inject_sandbox_xsrf(monkeypatch):
    """Do not reuse code sandbox XSRF headers for document server requests."""
    set_config(
        document_url=DOCUMENT_URL,
        code_sandbox_url=SANDBOX_URL,
        code_sandbox_token=SANDBOX_TOKEN,
    )
    document_client = FakeServerClient()
    stub = SimpleNamespace(document_client=document_client, document_auth_headers={})
    monkeypatch.setattr(ServerContext, "get_instance", lambda: stub)
    nm = NotebookManager()

    with patch.object(
        use_notebook_tool, "create_jupyter_sandbox_client", return_value=FakeKernel()
    ):
        await _execute(
            FakeServerClient(),
            nm,
            use_mode="create",
            auth_headers={"Cookie": "_xsrf=sandbox", "X-XSRFToken": "sandbox-xsrf"},
        )

    assert "work/nb.ipynb" in document_client.contents.created
    assert "X-XSRFToken" not in document_client.http_client.session.headers

    # The sandbox token must not leak to the (anonymous) document server.
    notebook_info = nm.get_notebook_connection("nb").notebook_info
    assert notebook_info["server_url"] == DOCUMENT_URL
    assert notebook_info["token"] is None


@pytest.mark.asyncio
async def test_split_opens_ui_on_document_server(monkeypatch):
    """Open the notebook in the document server's JupyterLab."""
    set_config(
        document_url=DOCUMENT_URL,
        document_token=DOCUMENT_TOKEN,
        code_sandbox_url=SANDBOX_URL,
        code_sandbox_token=SANDBOX_TOKEN,
        open_notebook_in_ui=True,
    )
    get_server_context().update(context_type="MCP_SERVER", jupyterlab=True)
    document_client = FakeServerClient(["nb.ipynb"])
    stub = SimpleNamespace(document_client=document_client, document_auth_headers={})
    monkeypatch.setattr(ServerContext, "get_instance", lambda: stub)
    nm = NotebookManager()

    FakeMCPToolsClient.calls = []
    monkeypatch.setattr("jupyter_mcp_tools.client.MCPToolsClient", FakeMCPToolsClient)

    with patch.object(
        use_notebook_tool, "create_jupyter_sandbox_client", return_value=FakeKernel()
    ):
        await _execute(FakeServerClient(), nm)

    assert FakeMCPToolsClient.calls == [
        (DOCUMENT_URL, DOCUMENT_TOKEN),
        ("docmanager_open", {"path": "work/nb.ipynb"}),
    ]

    # The registered token is the explicit document_token, not the sandbox's.
    notebook_info = nm.get_notebook_connection("nb").notebook_info
    assert notebook_info["server_url"] == DOCUMENT_URL
    assert notebook_info["token"] == DOCUMENT_TOKEN


@pytest.mark.asyncio
async def test_same_url_keeps_caller_client(monkeypatch):
    """Keep the caller's client when both server URLs match."""
    set_config(
        document_url=SANDBOX_URL,
        code_sandbox_url=SANDBOX_URL,
        code_sandbox_token=SANDBOX_TOKEN,
    )

    def _fail():
        raise AssertionError("ServerContext.get_instance must not be called")

    monkeypatch.setattr(ServerContext, "get_instance", _fail)
    client = FakeServerClient(["nb.ipynb"])
    nm = NotebookManager()

    with patch.object(
        use_notebook_tool, "create_jupyter_sandbox_client", return_value=FakeKernel()
    ):
        result = await _execute(client, nm)

    assert "Successfully activate notebook 'nb'" in result
    assert client.contents.listed == ["work"]


@pytest.mark.asyncio
async def test_unset_document_url_keeps_caller_client(monkeypatch):
    """Keep the caller's client and register the sandbox URL/token when
    document_url is unset (the sandbox-only engine shape)."""
    set_config(
        code_sandbox_url=SANDBOX_URL,
        code_sandbox_token=SANDBOX_TOKEN,
    )
    assert get_config().document_url is None

    def _fail():
        raise AssertionError("ServerContext.get_instance must not be called")

    monkeypatch.setattr(ServerContext, "get_instance", _fail)
    client = FakeServerClient(["nb.ipynb"])
    nm = NotebookManager()

    with patch.object(
        use_notebook_tool, "create_jupyter_sandbox_client", return_value=FakeKernel()
    ):
        result = await _execute(client, nm)

    assert "Successfully activate notebook 'nb'" in result
    assert client.contents.listed == ["work"]

    notebook_info = nm.get_notebook_connection("nb").notebook_info
    assert notebook_info["server_url"] == SANDBOX_URL
    assert notebook_info["token"] == SANDBOX_TOKEN


@pytest.fixture(scope="module")
def document_root(tmp_path_factory):
    return tmp_path_factory.mktemp("split_document_content")


@pytest.fixture(scope="module")
def document_server(document_root):
    """A second Jupyter Server, holding the notebook files."""
    host = "localhost"
    port = _find_free_port()
    yield from _start_server(
        name="JupyterLab-document",
        host=host,
        port=port,
        command=[
            "jupyter",
            "lab",
            "--port",
            str(port),
            "--IdentityProvider.token",
            JUPYTER_TOKEN,
            "--ip",
            host,
            "--ServerApp.root_dir",
            str(document_root),
            "--no-browser",
        ],
        readiness_endpoint="/api",
        max_retries=10,
    )


@pytest.fixture
def _reset_server_context():
    ServerContext.reset()
    yield
    ServerContext.reset()


@pytest.mark.asyncio
async def test_create_writes_to_document_server_not_sandbox(
    document_server, jupyter_server, _reset_server_context
):
    """use_mode="create" must put the file on the document server only."""
    set_config(
        document_url=document_server,
        document_token=JUPYTER_TOKEN,
        code_sandbox_url=jupyter_server,
        code_sandbox_token=JUPYTER_TOKEN,
    )
    context = ServerContext.get_instance()
    document_client = context.document_client

    await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=context.server_client,
        notebook_manager=NotebookManager(),
        notebook_name="split",
        notebook_path="split_create.ipynb",
        use_mode="create",
        code_sandbox_url=jupyter_server,
        code_sandbox_token=JUPYTER_TOKEN,
        auth_headers=None,
    )

    document_names = [f.name for f in document_client.contents.list_directory("")]
    sandbox_names = [f.name for f in context.server_client.contents.list_directory("")]
    assert "split_create.ipynb" in document_names
    assert "split_create.ipynb" not in sandbox_names


@pytest.mark.asyncio
async def test_connect_to_notebook_only_on_the_document_server(
    document_server, document_root, jupyter_server, _reset_server_context
):
    """The #344 repro: before the fix, the existence check and the
    collaboration session went to the code sandbox, which has no copy of the
    file, so this failed with a 404 on /api/collaboration/session/.
    """
    (document_root / "split_connect.ipynb").write_text(nbformat.writes(nbformat.v4.new_notebook()))

    set_config(
        document_url=document_server,
        document_token=JUPYTER_TOKEN,
        code_sandbox_url=jupyter_server,
        code_sandbox_token=JUPYTER_TOKEN,
    )
    context = ServerContext.get_instance()
    notebook_manager = NotebookManager()

    result = await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=context.server_client,
        notebook_manager=notebook_manager,
        notebook_name="connect",
        notebook_path="split_connect.ipynb",
        use_mode="connect",
        code_sandbox_url=jupyter_server,
        code_sandbox_token=JUPYTER_TOKEN,
        auth_headers=None,
    )

    assert "Successfully activate notebook 'connect'" in result
    assert (
        notebook_manager.get_notebook_connection("connect").notebook_info["server_url"]
        == document_server
    )

    # execute() swallows collaboration failures, so connect explicitly: this is
    # the request that returned the 404 in #344.
    async with notebook_manager.get_current_connection() as notebook:
        assert notebook is not None
