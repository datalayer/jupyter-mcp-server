# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests that use_notebook and unuse_notebook report "started" and "stopped"
to the hooks only when the notebook was actually activated or released.

Both events used to be fired by the server after the tool returned, whatever
the tool had answered, so a refused use_notebook or an unuse_notebook on a
notebook that was never connected landed in every audit sink and OTel span
file as a kernel start or stop. No running Jupyter server is required.
"""

from types import SimpleNamespace

import pytest

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.unuse_notebook_tool import UnuseNotebookTool
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool


class RecordingHandler:
    """Records every KERNEL_LIFECYCLE event as (event_type, kernel_id)."""

    def __init__(self):
        self.propagate_errors = False
        self.lifecycle: list[tuple[str, str]] = []

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        if event is HookEvent.KERNEL_LIFECYCLE:
            self.lifecycle.append((kwargs.get("event_type"), kwargs.get("kernel_id")))


@pytest.fixture
def handler():
    HookRegistry.reset()
    recording = RecordingHandler()
    HookRegistry.get_instance().register(recording)
    yield recording
    HookRegistry.reset()


@pytest.fixture
def manager():
    """Two connected notebooks, "first" current, on known backends.

    The datalayer provider keeps the Jupyter connectivity and path prechecks
    out of the way, as in test_use_notebook_already_connected.py.
    """
    from jupyter_mcp_server.config import reset_config, set_config

    reset_config()
    set_config(document_provider="datalayer", sandbox_variant="datalayer")
    nm = NotebookManager()
    nm.add_notebook("first", {"id": "sb-first"}, server_url="http://x", path="first.ipynb")
    nm.add_notebook("second", {"id": "sb-second"}, server_url="http://x", path="second.ipynb")
    nm.set_current_notebook("first")
    yield nm
    reset_config()


async def _use(nm, name, path):
    return await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=SimpleNamespace(),
        notebook_manager=nm,
        notebook_name=name,
        notebook_path=path,
        use_mode="connect",
    )


async def _unuse(nm, name):
    return await UnuseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=nm,
        notebook_name=name,
    )


@pytest.mark.asyncio
async def test_activating_a_notebook_is_reported_once(handler, manager):
    reply = await _use(manager, "second", "second.ipynb")

    assert "Reactivating notebook 'second'" in reply
    assert handler.lifecycle == [("started", "sb-second")]


@pytest.mark.asyncio
async def test_an_already_connected_notebook_is_not_reported(handler, manager):
    reply = await _use(manager, "first", "first.ipynb")

    assert "already connected" in reply
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_a_wrong_path_is_not_reported(handler, manager):
    reply = await _use(manager, "second", "elsewhere.ipynb")

    assert "is not the correct path" in reply
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_releasing_a_notebook_is_reported_under_its_kernel(handler, manager):
    reply = await _unuse(manager, "second")

    assert "unused successfully" in reply
    assert handler.lifecycle == [("stopped", "sb-second")]


@pytest.mark.asyncio
async def test_an_unknown_notebook_is_not_reported(handler, manager):
    reply = await _unuse(manager, "ghost")

    assert "is not connected" in reply
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_the_server_tools_report_exactly_what_the_tools_did(handler, manager, monkeypatch):
    """Through the registered MCP tools: refusals leave no lifecycle event
    behind, and each successful call leaves exactly one."""
    import jupyter_mcp_server.server as server

    monkeypatch.setattr(server, "notebook_manager", manager)
    monkeypatch.setattr(server.server_context, "_mode", ServerMode.MCP_SERVER)
    monkeypatch.setattr(server.server_context, "_kernel_manager", None)
    monkeypatch.setattr(server.server_context, "_initialized", True)

    refused = await server.use_notebook(notebook_name="first", notebook_path="first.ipynb")
    assert "already connected" in refused.content[0].text
    missing = await server.unuse_notebook(notebook_name="ghost")
    assert "is not connected" in missing.content[0].text
    assert handler.lifecycle == []

    await server.use_notebook(notebook_name="second", notebook_path="second.ipynb")
    await server.unuse_notebook(notebook_name="first")
    assert handler.lifecycle == [("started", "sb-second"), ("stopped", "sb-first")]
