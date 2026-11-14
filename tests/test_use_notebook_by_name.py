# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for use_notebook_by_name, optional notebook_name on use_notebook,
and ExecuteCellTool._start_and_bind_kernel internal signature simplification.
"""

from types import SimpleNamespace
from typing import Any

import nbformat
import pytest

from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool
from jupyter_mcp_server.tools.use_notebook_by_name_tool import UseNotebookByNameTool
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool


class RecordingHandler:
    """Records every KERNEL_LIFECYCLE event as (event_type, kernel_id)."""

    def __init__(self) -> None:
        self.propagate_errors = False
        self.lifecycle: list[tuple[str | None, str | None]] = []

    async def on_event(self, event: HookEvent, **kwargs: Any) -> None:
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
    reset_config()
    set_config(
        document_provider="datalayer",
        sandbox_variant="datalayer",
        document_url="http://x",
        code_sandbox_url="http://x",
    )
    nm = NotebookManager()
    nm.add_notebook("first", {"id": "sb-first"}, server_url="http://x", path="dir/first.ipynb")
    nm.add_notebook("second", {"id": "sb-second"}, server_url="http://x", path="dir/second.ipynb")
    nm.set_current_notebook("first")
    yield nm
    reset_config()


@pytest.mark.asyncio
async def test_use_notebook_by_name_switches_active_notebook(handler, manager):
    reply = await UseNotebookByNameTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=manager,
        notebook_name="second",
    )

    assert "Reactivating notebook 'second' and deactivating 'first'." in reply
    assert manager.get_current_notebook() == "second"
    assert handler.lifecycle == [("started", "sb-second")]


@pytest.mark.asyncio
async def test_use_notebook_by_name_unknown_notebook_refused(handler, manager):
    reply = await UseNotebookByNameTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=manager,
        notebook_name="missing",
    )

    assert "Notebook 'missing' is not connected." in reply
    assert "first" in reply and "second" in reply
    assert manager.get_current_notebook() == "first"
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_use_notebook_by_name_already_active_is_noop(handler, manager):
    reply = await UseNotebookByNameTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=manager,
        notebook_name="first",
    )

    assert "already active" in reply
    assert "sb-first" in reply
    assert manager.get_current_notebook() == "first"
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_use_notebook_by_name_local_mode_reads_preview(handler):
    reset_config()
    try:
        nm = NotebookManager()
        nm.add_notebook("alpha", {"id": "k-alpha"}, server_url="local", path="alpha.ipynb")
        nm.add_notebook("beta", {"id": "k-beta"}, server_url="local", path="sub/beta.ipynb")
        nm.set_current_notebook("alpha")

        nb_content = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("x = 42")]
        )

        class FakeContentsManager:
            def get(self, path: str, content: bool = True, **kwargs: Any) -> dict[str, Any]:
                assert path == "sub/beta.ipynb"
                assert content is True
                assert kwargs.get("type", "notebook") == "notebook"
                return {"content": nb_content}

        reply = await UseNotebookByNameTool().execute(
            mode=ServerMode.JUPYTER_SERVER,
            contents_manager=FakeContentsManager(),
            notebook_manager=nm,
            notebook_name="beta",
        )

        assert "Reactivating notebook 'beta' and deactivating 'alpha'." in reply
        assert "Notebook has 1 cells." in reply
        assert nm.get_current_notebook() == "beta"
        assert handler.lifecycle == [("started", "k-beta")]
    finally:
        reset_config()


@pytest.mark.asyncio
async def test_use_notebook_optional_name_defaults_to_path_and_reuses_alias(handler, manager):
    nm = NotebookManager()
    reply = await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=SimpleNamespace(),
        notebook_manager=nm,
        notebook_path="folder/analysis.ipynb",
        code_sandbox_url="http://x",
    )

    assert "Successfully activate notebook 'folder/analysis.ipynb'." in reply
    assert "folder/analysis.ipynb" in nm
    assert nm.get_current_notebook() == "folder/analysis.ipynb"

    # When a notebook was registered with an explicit alias, calling use_notebook
    # with only notebook_path resolves that existing alias instead of duplicating it.
    manager.set_current_notebook("first")
    reactivated = await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=SimpleNamespace(),
        notebook_manager=manager,
        notebook_path="dir/second.ipynb",
        code_sandbox_url="http://x",
    )

    assert "Reactivating notebook 'second' and deactivating 'first'." in reactivated
    assert manager.get_current_notebook() == "second"


@pytest.mark.asyncio
async def test_server_use_notebook_and_use_notebook_by_name_round_trip(
    handler, manager, monkeypatch
):
    import jupyter_mcp_server.server as server

    monkeypatch.setattr(server, "notebook_manager", manager)
    monkeypatch.setattr(server.server_context, "_mode", ServerMode.MCP_SERVER)
    monkeypatch.setattr(server.server_context, "_kernel_manager", None)
    monkeypatch.setattr(server.server_context, "_initialized", True)

    switched = await server.use_notebook_by_name(notebook_name="second")
    assert "Reactivating notebook 'second'" in switched.content[0].text
    assert manager.get_current_notebook() == "second"

    back = await server.use_notebook_by_name(notebook_name="first")
    assert "Reactivating notebook 'first'" in back.content[0].text
    assert manager.get_current_notebook() == "first"


@pytest.mark.asyncio
async def test_start_and_bind_kernel_resolves_path_from_notebook_name(monkeypatch):
    import asyncio as _asyncio

    async def _fast_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(_asyncio, "sleep", _fast_sleep)

    nm = NotebookManager()
    nm.add_notebook("nb_a", None, server_url="local", path="dir_a/a.ipynb")
    nm.add_notebook("nb_b", None, server_url="local", path="dir_b/b.ipynb")
    nm.set_current_notebook("nb_a")

    started_paths: list[str | None] = []

    class FakeKernelManager:
        async def start_kernel(self, path: str | None = None) -> str:
            started_paths.append(path)
            return f"kid-{len(started_paths)}"

    km = FakeKernelManager()
    tool = ExecuteCellTool()

    kid_b = await tool._start_and_bind_kernel(km, nm, notebook_name="nb_b")
    assert kid_b == "kid-1"
    assert started_paths == ["dir_b/b.ipynb"]
    assert nm.get_code_sandbox_id("nb_b") == "kid-1"
    assert nm.get_notebook_path("nb_b") == "dir_b/b.ipynb"

    kid_a = await tool._start_and_bind_kernel(km, nm)
    assert kid_a == "kid-2"
    assert started_paths == ["dir_b/b.ipynb", "dir_a/a.ipynb"]
    assert nm.get_code_sandbox_id("nb_a") == "kid-2"
    assert nm.get_notebook_path("nb_a") == "dir_a/a.ipynb"
