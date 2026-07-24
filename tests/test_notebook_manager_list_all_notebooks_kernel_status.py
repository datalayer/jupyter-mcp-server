# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for NotebookManager.list_all_notebooks kernel_status reporting.

These use an in-memory NotebookManager with minimal kernel/kernel-manager
stand-ins, so no running Jupyter server is required.
"""

from jupyter_mcp_server.notebook_manager import NotebookManager


class FakeKernelClient:
    """MCP_SERVER-mode kernel: has is_alive()."""

    def __init__(self, alive=True):
        self._alive = alive

    def is_alive(self):
        return self._alive


class FakeServerKernelManager:
    """Stand-in for the Jupyter server's real kernel manager: liveness is
    queried via `kernel_id in kernel_manager`, as restart_notebook_tool.py and
    use_notebook_tool.py already do for JUPYTER_SERVER mode."""

    def __init__(self, live_ids):
        self._live_ids = set(live_ids)

    def __contains__(self, kernel_id):
        return kernel_id in self._live_ids


def test_list_all_notebooks_mcp_server_mode_kernel_status_unaffected():
    """MCP_SERVER-mode kernels (KernelClient-shaped) keep using is_alive(),
    regardless of whether a kernel_manager is passed."""
    nm = NotebookManager()
    nm.add_notebook("alive-nb", FakeKernelClient(alive=True))
    nm.add_notebook("dead-nb", FakeKernelClient(alive=False))

    result = nm.list_all_notebooks()

    assert result["alive-nb"]["kernel_status"] == "alive"
    assert result["dead-nb"]["kernel_status"] == "dead"


def test_list_all_notebooks_jupyter_server_mode_reports_alive_kernel():
    """JUPYTER_SERVER-mode kernels are a plain dict ({"id": kernel_id}), not a
    KernelClient. Without a kernel_manager to consult, hasattr(kernel,
    'is_alive') is always False, so this used to report 'dead' unconditionally
    even for a kernel that is actually running."""
    nm = NotebookManager()
    nm.add_notebook("nb", {"id": "kernel-123"}, server_url="local")
    kernel_manager = FakeServerKernelManager(live_ids=["kernel-123"])

    result = nm.list_all_notebooks(kernel_manager=kernel_manager)

    assert result["nb"]["kernel_status"] == "alive"


def test_list_all_notebooks_jupyter_server_mode_reports_dead_kernel():
    """A JUPYTER_SERVER-mode kernel that the real kernel manager no longer
    knows about (culled/restarted) still reports 'dead'."""
    nm = NotebookManager()
    nm.add_notebook("nb", {"id": "kernel-gone"}, server_url="local")
    kernel_manager = FakeServerKernelManager(live_ids=[])

    result = nm.list_all_notebooks(kernel_manager=kernel_manager)

    assert result["nb"]["kernel_status"] == "dead"


def test_list_all_notebooks_jupyter_server_mode_without_kernel_manager_is_unknown():
    """Without a kernel_manager to consult (e.g. an older caller), a
    dict-shaped kernel is honestly reported 'unknown' rather than the old
    silent-'dead' default."""
    nm = NotebookManager()
    nm.add_notebook("nb", {"id": "kernel-123"}, server_url="local")

    result = nm.list_all_notebooks()

    assert result["nb"]["kernel_status"] == "unknown"
