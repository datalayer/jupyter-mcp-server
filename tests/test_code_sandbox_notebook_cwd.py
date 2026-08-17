# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""MCP_SERVER-mode kernels start in the notebook's own directory.

Jupyter Server derives a kernel's working directory from the ``path`` sent to
``POST /api/kernels``, so a sandbox built without one runs in the server root
and every relative path inside the notebook resolves against the wrong place.
"""

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

SANDBOX_URL = "http://sandbox.example"
NB_PATH = "projects/demo/notebook.ipynb"


class FakeKernel:
    id = "kernel-1"

    def __init__(self, alive=True):
        self._alive = alive

    def is_alive(self):
        return self._alive


class _FakeContents:
    @staticmethod
    def create_notebook(path, content=None):
        return None

    @staticmethod
    def list_directory(path):
        return [SimpleNamespace(name="notebook.ipynb")]

    @staticmethod
    def get(path):
        return {"content": {"cells": []}}


class _FakeKernels:
    @staticmethod
    def list_kernels():
        return []


class FakeServerClient:
    contents = _FakeContents
    kernels = _FakeKernels

    def get_status(self):
        return {}


@pytest.fixture
def recorded_sandbox_kwargs(monkeypatch):
    """Capture what the shared factory hands the Jupyter sandbox client."""
    seen = {}

    def fake_client(**kwargs):
        seen.update(kwargs)
        return FakeKernel()

    monkeypatch.setattr(
        "jupyter_mcp_server.sandbox_client.create_jupyter_sandbox_client", fake_client
    )
    with patch("jupyter_mcp_server.extensions.get_extension_manager") as manager:
        manager.return_value.create_code_sandbox.return_value = None
        yield seen


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def test_the_factory_forwards_the_notebook_path(recorded_sandbox_kwargs):
    from jupyter_mcp_server import utils

    config = set_config(code_sandbox_url=SANDBOX_URL)
    utils.create_code_sandbox(config, logging.getLogger("test"), path=NB_PATH)

    assert recorded_sandbox_kwargs["path"] == NB_PATH


@pytest.mark.asyncio
async def test_use_notebook_starts_the_kernel_in_the_notebook_directory(
    monkeypatch, recorded_sandbox_kwargs
):
    """The eager path, taken whenever --start-new-code-sandbox is on (the default)."""
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=True)
    monkeypatch.setattr(
        "jupyter_mcp_server.server_context.ServerContext.get_instance",
        staticmethod(
            lambda: SimpleNamespace(
                document_server_client=FakeServerClient(),
                document_auth_headers={},
                code_sandbox_auth_headers={},
            )
        ),
    )

    await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=FakeServerClient(),
        notebook_manager=NotebookManager(),
        notebook_name="demo",
        notebook_path=NB_PATH,
        use_mode="connect",
        code_sandbox_url=SANDBOX_URL,
    )

    assert recorded_sandbox_kwargs["path"] == NB_PATH


def test_a_replacement_kernel_starts_in_the_current_notebooks_directory(
    monkeypatch, recorded_sandbox_kwargs
):
    """The deferred path: the first execution, and every culled-kernel replacement."""
    from jupyter_mcp_server import server

    set_config(code_sandbox_url=SANDBOX_URL)
    monkeypatch.setattr(
        "jupyter_mcp_server.server_context.ServerContext.get_instance",
        staticmethod(lambda: SimpleNamespace(code_sandbox_auth_headers={})),
    )
    notebook_manager = NotebookManager()
    notebook_manager.add_notebook(
        "demo", FakeKernel(alive=False), server_url=SANDBOX_URL, token=None, path=NB_PATH
    )
    notebook_manager.set_current_notebook("demo")
    monkeypatch.setattr(server, "notebook_manager", notebook_manager)

    getattr(server, "__ensure_code_sandbox_alive")()

    assert recorded_sandbox_kwargs["path"] == NB_PATH
