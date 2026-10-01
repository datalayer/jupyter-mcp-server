# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""MCP kernels are registered as Jupyter sessions when they are started (#478)."""

import logging
from types import SimpleNamespace

import pytest

from jupyter_mcp_server.capabilities import (
    KERNEL_ADOPT_SESSION,
    get_capabilities,
    reset_capabilities,
)
from jupyter_mcp_server.config import get_config, reset_config
from jupyter_mcp_server.server_context import ServerContext
from jupyter_mcp_server.utils import create_code_sandbox


class RecordingSessions:
    def __init__(self):
        self.created = []

    def create_session(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="session-for-kernel")


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    sessions = RecordingSessions()
    server_client = SimpleNamespace(sessions=sessions)
    context = SimpleNamespace(
        code_sandbox_auth_headers={},
        sandbox_server_client=server_client,
    )
    monkeypatch.setattr(ServerContext, "get_instance", classmethod(lambda cls: context))
    monkeypatch.setattr(
        "jupyter_mcp_server.extensions.get_extension_manager",
        lambda: SimpleNamespace(create_code_sandbox=lambda config, logger: None),
    )
    reset_capabilities()
    reset_config()
    yield sessions
    reset_capabilities()
    reset_config()


@pytest.fixture
def sandbox_factory(monkeypatch):
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(id="kernel-new", variant="jupyter-server")

    monkeypatch.setattr(
        "jupyter_mcp_server.sandbox_client.create_jupyter_sandbox_client", create
    )
    return seen


def _enable_adoption():
    get_capabilities().set(KERNEL_ADOPT_SESSION, True, source="cli")


def test_new_mcp_kernel_gets_a_session_for_its_notebook(fresh_state, sandbox_factory):
    """Opening the notebook in JupyterLab must find the kernel the agent started."""
    _enable_adoption()

    sandbox = create_code_sandbox(get_config(), logging.getLogger("test"), path="dir/nb.ipynb")

    assert sandbox.id == "kernel-new"
    assert fresh_state.created == [
        {
            "path": "dir/nb.ipynb",
            "kernel": {"id": "kernel-new"},
            "session_type": "notebook",
            "name": "dir/nb.ipynb",
        }
    ]


def test_existing_kernel_is_not_rebound_to_a_second_session(fresh_state, sandbox_factory):
    """Adopting an existing session's kernel must not create a duplicate."""
    _enable_adoption()

    create_code_sandbox(
        get_config(),
        logging.getLogger("test"),
        path="dir/nb.ipynb",
        code_sandbox_id="kernel-existing",
    )

    assert sandbox_factory["kernel_id"] == "kernel-existing"
    assert fresh_state.created == []


def test_session_creation_stays_off_without_the_capability(fresh_state, sandbox_factory):
    create_code_sandbox(get_config(), logging.getLogger("test"), path="dir/nb.ipynb")

    assert fresh_state.created == []
