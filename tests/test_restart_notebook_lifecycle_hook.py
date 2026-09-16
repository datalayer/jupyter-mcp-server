# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests that restart_notebook reports a "restarted" kernel to the hooks only
when a kernel actually restarted.

The lifecycle event used to be fired by the server after the tool returned,
whatever the tool had answered, so a failed restart was recorded as a restart
by every audit sink and OTel span file. These tests use the same in-memory
kernel-manager stand-in as test_restart_notebook_tool.py; no running Jupyter
server is required.
"""

import pytest

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.restart_notebook_tool import RestartNotebookTool


class RecordingHandler:
    """Records every KERNEL_LIFECYCLE event as (event_type, kernel_id)."""

    def __init__(self):
        self.propagate_errors = False
        self.lifecycle: list[tuple[str, str]] = []

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        if event is HookEvent.KERNEL_LIFECYCLE:
            self.lifecycle.append((kwargs.get("event_type"), kwargs.get("kernel_id")))


class FakeKernelManager:
    """Minimal stand-in for MappingKernelManager: membership, restart, start."""

    def __init__(self, existing_ids=(), restart_error=None, start_error=None):
        self._kernels = set(existing_ids)
        self._restart_error = restart_error
        self._start_error = start_error

    def __contains__(self, kernel_id):
        return kernel_id in self._kernels

    async def restart_kernel(self, kernel_id):
        if self._restart_error is not None:
            raise self._restart_error
        return None

    async def start_kernel(self, path=None, **kwargs):
        if self._start_error is not None:
            raise self._start_error
        self._kernels.add("kernel-new")
        return "kernel-new"


class FakeSandbox:
    """Stand-in for a code sandbox whose restart may fail."""

    def __init__(self, sandbox_id, error=None):
        self.id = sandbox_id
        self._error = error

    def restart(self):
        if self._error is not None:
            raise self._error


@pytest.fixture
def handler():
    HookRegistry.reset()
    recording = RecordingHandler()
    HookRegistry.get_instance().register(recording)
    yield recording
    HookRegistry.reset()


def _jupyter_server_manager(kernel_id):
    nm = NotebookManager()
    nm.add_notebook("nb", {"id": kernel_id}, server_url="local", token=None, path="nb.ipynb")
    return nm


async def _restart(mode, notebook_manager, kernel_manager=None, name="nb"):
    return await RestartNotebookTool().execute(
        mode=mode,
        kernel_manager=kernel_manager,
        notebook_manager=notebook_manager,
        notebook_name=name,
    )


@pytest.mark.asyncio
async def test_a_successful_restart_is_reported_once(handler):
    nm = _jupyter_server_manager("k1")

    result = await _restart(ServerMode.JUPYTER_SERVER, nm, FakeKernelManager(["k1"]))

    assert "restarted successfully" in result
    assert handler.lifecycle == [("restarted", "k1")]


@pytest.mark.asyncio
async def test_a_reprovisioned_kernel_is_reported_under_its_new_id(handler):
    nm = _jupyter_server_manager("culled")

    result = await _restart(ServerMode.JUPYTER_SERVER, nm, FakeKernelManager([]))

    assert "reprovisioned" in result
    assert handler.lifecycle == [("restarted", "kernel-new")]


@pytest.mark.asyncio
async def test_a_restart_the_kernel_manager_rejects_is_not_reported(handler):
    nm = _jupyter_server_manager("k1")
    km = FakeKernelManager(["k1"], restart_error=RuntimeError("kernel is busy"))

    result = await _restart(ServerMode.JUPYTER_SERVER, nm, km)

    assert result.startswith("Failed to restart notebook 'nb'")
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_a_failed_reprovision_is_not_reported(handler):
    nm = _jupyter_server_manager("culled")
    km = FakeKernelManager([], start_error=RuntimeError("no kernelspec"))

    result = await _restart(ServerMode.JUPYTER_SERVER, nm, km)

    assert "reprovisioning failed" in result
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_a_sandbox_that_fails_to_restart_is_not_reported(handler):
    nm = NotebookManager()
    nm.add_notebook("nb", FakeSandbox("sb-1", error=RuntimeError("boom")))

    result = await _restart(ServerMode.MCP_SERVER, nm)

    assert result.startswith("Failed to restart notebook 'nb'")
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_a_sandbox_that_restarts_is_reported(handler):
    nm = NotebookManager()
    nm.add_notebook("nb", FakeSandbox("sb-1"))

    result = await _restart(ServerMode.MCP_SERVER, nm)

    assert "restarted successfully" in result
    assert handler.lifecycle == [("restarted", "sb-1")]


@pytest.mark.asyncio
async def test_an_unknown_notebook_is_not_reported(handler):
    nm = NotebookManager()
    nm.add_notebook("nb", FakeSandbox("sb-1"))

    result = await _restart(ServerMode.MCP_SERVER, nm, name="ghost")

    assert "is not connected" in result
    assert handler.lifecycle == []


@pytest.mark.asyncio
async def test_the_server_tool_reports_exactly_what_the_tool_did(handler, monkeypatch):
    """Through the registered MCP tool: a failed restart leaves no lifecycle
    event behind, and a successful one leaves exactly one."""
    import jupyter_mcp_server.server as server

    nm = NotebookManager()
    nm.add_notebook("broken", FakeSandbox("sb-broken", error=RuntimeError("boom")))
    nm.add_notebook("fine", FakeSandbox("sb-fine"))
    monkeypatch.setattr(server, "notebook_manager", nm)
    monkeypatch.setattr(server.server_context, "_mode", ServerMode.MCP_SERVER)
    monkeypatch.setattr(server.server_context, "_kernel_manager", None)
    monkeypatch.setattr(server.server_context, "_initialized", True)

    failed = await server.restart_notebook(notebook_name="broken")
    assert "Failed to restart notebook 'broken'" in failed.content[0].text
    assert handler.lifecycle == []

    restarted = await server.restart_notebook(notebook_name="fine")
    assert "restarted successfully" in restarted.content[0].text
    assert handler.lifecycle == [("restarted", "sb-fine")]
