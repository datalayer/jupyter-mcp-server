# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for RestartNotebookTool self-healing in JUPYTER_SERVER mode.

These tests exercise the tool's kernel-liveness handling with a minimal
in-memory stand-in for jupyter_server's MappingKernelManager, so no running
Jupyter server is required.
"""

import pytest

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.restart_notebook_tool import RestartNotebookTool


class FakeKernelManager:
    """Minimal stand-in for MappingKernelManager covering the surface
    restart_notebook uses: membership, restart, and start_kernel."""

    def __init__(self, existing_ids=()):
        self._kernels = set(existing_ids)
        self._counter = 0
        self.started_paths = []

    def __contains__(self, kernel_id):
        return kernel_id in self._kernels

    async def restart_kernel(self, kernel_id):
        if kernel_id not in self._kernels:
            # Mirror MappingKernelManager, which 404s on a missing kernel.
            raise Exception(f"HTTP 404: Not Found (Kernel does not exist: {kernel_id})")
        return None

    async def start_kernel(self, path=None, **kwargs):
        self._counter += 1
        new_id = f"kernel-new-{self._counter}"
        self._kernels.add(new_id)
        self.started_paths.append(path)
        return new_id


class RacyKernelManager(FakeKernelManager):
    """Kernel manager whose kernel is culled exactly during the restart call,
    so the liveness check passes but restart_kernel then 404s."""

    async def restart_kernel(self, kernel_id):
        self._kernels.discard(kernel_id)
        raise Exception(f"HTTP 404: Not Found (Kernel does not exist: {kernel_id})")


def _manager_with_notebook(kernel_id, path="work/test.ipynb"):
    nm = NotebookManager()
    nm.add_notebook(
        "nb",
        {"id": kernel_id},
        server_url="local",
        token=None,
        path=path,
    )
    return nm


@pytest.mark.asyncio
async def test_restart_reprovisions_when_kernel_culled():
    """A restart on a notebook whose kernel was culled must self-heal:
    provision a fresh kernel, rebind it, and report success."""
    nm = _manager_with_notebook("dead-kernel")
    km = FakeKernelManager(existing_ids=[])  # dead-kernel is gone

    result = await RestartNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        kernel_manager=km,
        notebook_manager=nm,
        notebook_name="nb",
    )

    assert "reprovisioned" in result
    assert "kernel-new-1" in result
    # The binding was rebound to the fresh kernel, not left stale.
    assert nm.get_kernel_id("nb") == "kernel-new-1"
    # The new kernel was started with the notebook's path (cwd), matching use_notebook.
    assert km.started_paths == ["work/test.ipynb"]


@pytest.mark.asyncio
async def test_restart_reprovisions_when_kernel_culled_during_restart():
    """If the kernel is culled between the liveness check and restart_kernel,
    the except branch must also self-heal rather than surface the 404."""
    nm = _manager_with_notebook("live-then-gone")
    km = RacyKernelManager(existing_ids=["live-then-gone"])

    result = await RestartNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        kernel_manager=km,
        notebook_manager=nm,
        notebook_name="nb",
    )

    assert "reprovisioned" in result
    assert nm.get_kernel_id("nb") == "kernel-new-1"


@pytest.mark.asyncio
async def test_restart_live_kernel_is_unchanged():
    """The happy path (kernel alive) restarts in place and keeps the same id."""
    nm = _manager_with_notebook("live")
    km = FakeKernelManager(existing_ids=["live"])

    result = await RestartNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        kernel_manager=km,
        notebook_manager=nm,
        notebook_name="nb",
    )

    assert "restarted successfully" in result
    assert nm.get_kernel_id("nb") == "live"
    assert km.started_paths == []  # no new kernel provisioned
