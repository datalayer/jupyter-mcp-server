# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for the server-side liveness check in ensure_code_sandbox_alive.

A Jupyter-backed sandbox keeps reporting `is_alive()` True after the server has
dropped its kernel, so the guard is driven from the server's kernel list. These
tests use a stand-in sandbox and a stubbed server client, so no running Jupyter
server is required.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.tools import ServerMode
from jupyter_mcp_server.utils import code_sandbox_is_alive, ensure_code_sandbox_alive


class FakeSandbox:
    """Stand-in for CodeSandboxClient exposing only what the guard reads."""

    def __init__(self, sandbox_id, variant="jupyter-server"):
        self.id = sandbox_id
        self.variant = variant

    def is_alive(self):
        return True


def _server_client_listing(*kernel_ids):
    client = MagicMock()
    client.kernels.list_kernels.return_value = [SimpleNamespace(id=k) for k in kernel_ids]
    return client


def _install_server_client(client):
    context = ServerContext.get_instance()
    context._mode = ServerMode.MCP_SERVER
    context._sandbox_server_client = client
    context._initialized = True
    return context


def setup_function():
    ServerContext.reset()
    ServerContext._instance = None


def teardown_function():
    ServerContext.reset()
    ServerContext._instance = None


def test_ensure_replaces_sandbox_whose_kernel_the_server_dropped():
    """The kernel is gone from the server, so the guard provisions a new sandbox."""
    _install_server_client(_server_client_listing())
    nm = NotebookManager()
    stale = FakeSandbox("culled-kernel")
    nm.add_notebook("nb", stale)

    result = ensure_code_sandbox_alive(nm, "nb", lambda: FakeSandbox("fresh-kernel"))

    assert result.id == "fresh-kernel"
    assert nm.get_code_sandbox_id("nb") == "fresh-kernel"


def test_ensure_keeps_sandbox_the_server_still_lists():
    """The kernel is still on the server, so nothing is provisioned."""
    _install_server_client(_server_client_listing("live-kernel", "someone-elses-kernel"))
    nm = NotebookManager()
    live = FakeSandbox("live-kernel")
    nm.add_notebook("nb", live)

    result = ensure_code_sandbox_alive(nm, "nb", lambda: FakeSandbox("should-not-be-used"))

    assert result is live


def test_lookup_failure_keeps_the_sandbox():
    """A failed kernel listing is not evidence that the kernel is gone."""
    client = MagicMock()
    client.kernels.list_kernels.side_effect = ConnectionError("server unreachable")
    _install_server_client(client)
    live = FakeSandbox("live-kernel")

    assert code_sandbox_is_alive(live) is True


def test_sandbox_that_reports_itself_dead_is_not_looked_up():
    """The sandbox's own answer is still enough to condemn it."""
    client = _server_client_listing("live-kernel")
    _install_server_client(client)
    stopped = FakeSandbox("live-kernel")
    stopped.is_alive = lambda: False

    assert code_sandbox_is_alive(stopped) is False
    client.kernels.list_kernels.assert_not_called()


def test_sandbox_is_kept_when_no_server_client_is_configured():
    """With nothing to ask, the previous behaviour stands."""
    context = _install_server_client(None)
    context._sandbox_server_client = None

    assert code_sandbox_is_alive(FakeSandbox("live-kernel")) is True


def test_non_jupyter_sandbox_is_not_checked_against_the_kernel_list():
    """Another variant does not run on this server, so its kernel list says nothing."""
    client = _server_client_listing()
    _install_server_client(client)

    assert code_sandbox_is_alive(FakeSandbox("sandbox-1", variant="e2b")) is True
    client.kernels.list_kernels.assert_not_called()
