# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Test that use_notebook reports a document server whose collaboration stack predates ours.

A pre-5 collaboration server applies an in-place scalar write to a cell as a
deletion of that key, so an executed cell reaches the saved notebook without its
execution_count. The remote version is read from /lab/api/extensions, and a probe
that cannot answer leaves the caller silent rather than reporting a healthy server.
"""

from importlib.metadata import version
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jupyter_mcp_server import sandbox_client
from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import (
    _COLLABORATION_VERDICTS,
    COLLABORATION_EXTENSION,
    UseNotebookTool,
)

SERVER_URL = "http://localhost:8888"
SERVER_TOKEN = "token"

LOCAL_MAJOR = int(version("jupyter-collaboration").split(".")[0])
OLDER_VERSION = f"{LOCAL_MAJOR - 1}.4.2"
CURRENT_VERSION = f"{LOCAL_MAJOR}.0.2"


class FakeFile:
    def __init__(self, name):
        self.name = name


class FakeContents:
    def __init__(self, names):
        self._names = names

    def list_directory(self, path):
        return [FakeFile(name) for name in self._names]


class FakeHTTPClient:
    """Answer /lab/api/extensions with a canned payload, or raise."""

    def __init__(self, extensions=None, error=None):
        self._extensions = extensions
        self._error = error
        self.session = SimpleNamespace(headers={})
        self.requested = []

    def request(self, method, path, **kwargs):
        self.requested.append((method, path))
        if self._error is not None:
            raise self._error
        return self._extensions


class FakeServerClient:
    def __init__(self, extensions=None, error=None):
        self.contents = FakeContents(["nb.ipynb"])
        self.http_client = FakeHTTPClient(extensions=extensions, error=error)

    def get_status(self):
        return {"version": "2.0.0"}


class FakeKernel:
    id = "kernel-1"


def _extensions(collaboration_version):
    return [
        {"name": "@jupyterlab/some-other-extension", "installed_version": "1.0.0"},
        {"name": COLLABORATION_EXTENSION, "installed_version": collaboration_version},
    ]


@pytest.fixture(autouse=True)
def _reset_config():
    # The verdict cache is process-wide, so every test starts from a cold one.
    # Without this the first test to warn answers for all the later ones.
    reset_config()
    _COLLABORATION_VERDICTS.clear()
    yield
    _COLLABORATION_VERDICTS.clear()
    reset_config()


async def _use_notebook(server_client):
    set_config(
        document_url=SERVER_URL, code_sandbox_url=SERVER_URL, code_sandbox_token=SERVER_TOKEN
    )
    with patch.object(sandbox_client, "create_jupyter_sandbox_client", return_value=FakeKernel()):
        return await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=server_client,
            notebook_manager=NotebookManager(),
            notebook_name="nb",
            notebook_path="nb.ipynb",
            use_mode="connect",
            code_sandbox_url=SERVER_URL,
            code_sandbox_token=SERVER_TOKEN,
        )


@pytest.mark.asyncio
async def test_warns_when_document_server_collaboration_is_older():
    """An older remote collaboration major is reported to the caller."""
    server_client = FakeServerClient(extensions=_extensions(OLDER_VERSION))

    result = await _use_notebook(server_client)

    assert ("GET", "/lab/api/extensions") in server_client.http_client.requested
    assert "[WARNING]" in result
    assert OLDER_VERSION in result
    assert "execution_count" in result


@pytest.mark.asyncio
async def test_silent_when_document_server_collaboration_is_current():
    """A remote on our own major raises nothing."""
    server_client = FakeServerClient(extensions=_extensions(CURRENT_VERSION))

    result = await _use_notebook(server_client)

    assert "[WARNING]" not in result


@pytest.mark.asyncio
async def test_silent_when_extensions_endpoint_is_unavailable():
    """A probe that errors is unknown, not a healthy server."""
    server_client = FakeServerClient(error=RuntimeError("404 Not Found"))

    result = await _use_notebook(server_client)

    assert "[WARNING]" not in result


@pytest.mark.asyncio
async def test_silent_when_collaboration_extension_is_absent():
    """A payload without the collaboration extension is unknown, not a healthy server."""
    server_client = FakeServerClient(
        extensions=[{"name": "@jupyterlab/some-other-extension", "installed_version": "1.0.0"}]
    )

    result = await _use_notebook(server_client)

    assert "[WARNING]" not in result


@pytest.mark.asyncio
async def test_extension_list_is_fetched_once_per_server():
    """A second use_notebook against the same server reuses the first answer."""
    server_client = FakeServerClient(extensions=_extensions(OLDER_VERSION))

    first = await _use_notebook(server_client)
    second = await _use_notebook(server_client)

    probes = [path for method, path in server_client.http_client.requested]
    assert probes.count("/lab/api/extensions") == 1
    assert "[WARNING]" in first
    assert "[WARNING]" in second


@pytest.mark.asyncio
async def test_failed_probe_is_retried_rather_than_cached():
    """Silence from an unreachable server is not an answer, so it is not remembered."""
    failing = FakeServerClient(error=RuntimeError("connection refused"))
    assert "[WARNING]" not in await _use_notebook(failing)

    recovered = FakeServerClient(extensions=_extensions(OLDER_VERSION))
    result = await _use_notebook(recovered)

    assert ("GET", "/lab/api/extensions") in recovered.http_client.requested
    assert "[WARNING]" in result
