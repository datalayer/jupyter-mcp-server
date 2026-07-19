# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for NotebookManager.ensure_kernel_alive kernel regeneration.

These tests use an in-memory NotebookManager with minimal KernelClient
stand-ins, so no running Jupyter server is required.
"""

from jupyter_mcp_server.notebook_manager import NotebookManager

# A non-default binding, as use_notebook records in MCP_SERVER mode. Held in
# constants (not call-site literals) so the "token" argument reads as data.
RUNTIME_URL = "https://runtime.example/"
RUNTIME_AUTH = "runtime-token"
NB_PATH = "work/analysis.ipynb"


class FakeKernel:
    """Minimal KernelClient stand-in exposing only the liveness surface that
    ensure_kernel_alive checks (`is_alive`), plus an id for identity asserts."""

    def __init__(self, kernel_id, alive=True):
        self.id = kernel_id
        self._alive = alive

    def is_alive(self):
        return self._alive


def _manager_with_bound_notebook():
    """A notebook bound to an explicit (non-default) server_url/token/path,
    as use_notebook does in MCP_SERVER mode, with a dead kernel."""
    nm = NotebookManager()
    nm.add_notebook(
        "nb",
        FakeKernel("dead-kernel", alive=False),
        server_url=RUNTIME_URL,
        token=RUNTIME_AUTH,
        path=NB_PATH,
    )
    return nm


def test_ensure_kernel_alive_preserves_binding_on_restart():
    """Regenerating a dead kernel must keep the notebook's server_url/token/path
    binding, and swap in the fresh kernel."""
    nm = _manager_with_bound_notebook()

    new_kernel = nm.ensure_kernel_alive("nb", lambda: FakeKernel("fresh-kernel"))

    # The fresh kernel is installed and returned.
    assert new_kernel.id == "fresh-kernel"
    assert nm.get_kernel_id("nb") == "fresh-kernel"

    # The binding survives the restart (this is what regressed): it must NOT
    # fall back to the config defaults.
    info = nm.get_notebook_connection("nb").notebook_info
    assert info["server_url"] == RUNTIME_URL
    assert info["token"] == RUNTIME_AUTH
    assert info["path"] == NB_PATH
    assert nm.get_notebook_path("nb") == NB_PATH


def test_ensure_kernel_alive_keeps_live_kernel():
    """A live kernel is returned unchanged, and the binding is untouched."""
    nm = NotebookManager()
    live = FakeKernel("live-kernel", alive=True)
    nm.add_notebook(
        "nb", live,
        server_url=RUNTIME_URL, token=RUNTIME_AUTH, path=NB_PATH,
    )

    result = nm.ensure_kernel_alive("nb", lambda: FakeKernel("should-not-be-used"))

    assert result is live
    assert nm.get_notebook_path("nb") == NB_PATH


def test_ensure_kernel_alive_adds_notebook_when_absent():
    """When the notebook is not yet tracked, a kernel is provisioned via the
    normal add_notebook path (fallback branch)."""
    nm = NotebookManager()

    new_kernel = nm.ensure_kernel_alive("fresh", lambda: FakeKernel("k1"))

    assert new_kernel.id == "k1"
    assert "fresh" in nm
    assert nm.get_kernel_id("fresh") == "k1"
