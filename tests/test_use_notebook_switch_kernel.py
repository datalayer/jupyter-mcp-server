# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Switching the kernel assigned to an already-connected notebook (#329)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import NEW_KERNEL_ID, UseNotebookTool

SANDBOX_URL = "http://sandbox.example"
KERNEL_A = "kernel-alpha"
KERNEL_B = "kernel-beta"
NB_PATH = "nb.ipynb"
OTHER_PATH = "other.ipynb"


class FakeContents:
    @staticmethod
    def list_directory(path):
        return [SimpleNamespace(name=NB_PATH), SimpleNamespace(name=OTHER_PATH)]

    @staticmethod
    def get(path):
        return {"content": {"cells": []}}


class FakeKernels:
    def __init__(self, ids=()):
        self._ids = list(ids)

    def list_kernels(self):
        return [SimpleNamespace(id=kernel_id) for kernel_id in self._ids]


class FakeSessions:
    def __init__(self, sessions=()):
        self._sessions = list(sessions)
        self.created: list[dict] = []

    def list_sessions(self):
        return self._sessions

    def create_session(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="session-created")


class FakeServerClient:
    def __init__(self, *, kernels=(), sessions=()):
        self.contents = FakeContents()
        self.kernels = FakeKernels(kernels)
        self.sessions = FakeSessions(sessions)

    @staticmethod
    def get_status():
        return {}


class FakeExtensionManager:
    def __init__(self):
        self.created_with: list[str | None] = []
        self.created_new = 0

    def get_active_code_sandbox(self, config, logger):
        return None

    def create_code_sandbox(self, config, logger):
        self.created_with.append(config.code_sandbox_id)
        return SimpleNamespace(id=config.code_sandbox_id or "kernel-new", is_alive=lambda: True)

    def create_new_code_sandbox(self, config, logger):
        self.created_new += 1
        return SimpleNamespace(id=f"kernel-isolated-{self.created_new}", is_alive=lambda: True)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr("jupyter_mcp_server.watchers.watchers.watch", lambda name, manager: False)
    reset_config()
    yield
    reset_config()


@pytest.mark.asyncio
async def test_switch_kernel_on_current_notebook_mcp_server():
    """Passing a different kernel_id on an already-connected notebook switches its kernel."""
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=False)
    client = FakeServerClient(kernels=[KERNEL_A, KERNEL_B])
    ext_mgr = FakeExtensionManager()
    notebook_manager = NotebookManager()

    with patch("jupyter_mcp_server.extensions.get_extension_manager", return_value=ext_mgr):
        first = await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_A,
        )
        assert f"Connected to kernel '{KERNEL_A}'" in first
        assert notebook_manager.get_code_sandbox_id("demo") == KERNEL_A

        switched = await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_B,
        )

    assert f"Switched notebook 'demo' to kernel '{KERNEL_B}'" in switched
    assert notebook_manager.get_code_sandbox_id("demo") == KERNEL_B


@pytest.mark.asyncio
async def test_switch_kernel_to_new_isolated_kernel_mcp_server():
    """Passing kernel_id='NEW' on an already-connected notebook starts and binds a fresh kernel."""
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=False)
    client = FakeServerClient(kernels=[KERNEL_A])
    ext_mgr = FakeExtensionManager()
    notebook_manager = NotebookManager()

    with patch("jupyter_mcp_server.extensions.get_extension_manager", return_value=ext_mgr):
        await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_A,
        )
        switched = await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=NEW_KERNEL_ID,
        )

    assert "Switched notebook 'demo' to a new isolated kernel 'kernel-isolated-1'" in switched
    assert notebook_manager.get_code_sandbox_id("demo") == "kernel-isolated-1"
    assert ext_mgr.created_new == 1


@pytest.mark.asyncio
async def test_switch_kernel_refuses_unknown_kernel_and_preserves_binding():
    """Switching to a non-existent kernel fails cleanly without losing the existing binding."""
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=False)
    client = FakeServerClient(kernels=[KERNEL_A])
    ext_mgr = FakeExtensionManager()
    notebook_manager = NotebookManager()

    with patch("jupyter_mcp_server.extensions.get_extension_manager", return_value=ext_mgr):
        await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_A,
        )
        reply = await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id="no-such-kernel",
        )

    assert "not found" in reply
    assert notebook_manager.get_code_sandbox_id("demo") == KERNEL_A


@pytest.mark.asyncio
async def test_switch_kernel_while_reactivating_non_current_notebook():
    """Reactivating a non-current notebook with a new kernel_id both activates and switches it."""
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=False)
    client = FakeServerClient(kernels=[KERNEL_A, KERNEL_B])
    ext_mgr = FakeExtensionManager()
    notebook_manager = NotebookManager()

    with patch("jupyter_mcp_server.extensions.get_extension_manager", return_value=ext_mgr):
        await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_A,
        )
        await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="other",
            notebook_path=OTHER_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
        )
        assert notebook_manager.get_current_notebook() == "other"

        reply = await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_B,
        )

    assert f"Switched notebook 'demo' to kernel '{KERNEL_B}'" in reply
    assert "Reactivating notebook 'demo' and deactivating 'other'" in reply
    assert notebook_manager.get_current_notebook() == "demo"
    assert notebook_manager.get_code_sandbox_id("demo") == KERNEL_B


@pytest.mark.asyncio
async def test_passing_same_kernel_id_reports_already_connected():
    """Passing the same kernel_id the notebook is already bound to reports already connected."""
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=False)
    client = FakeServerClient(kernels=[KERNEL_A])
    ext_mgr = FakeExtensionManager()
    notebook_manager = NotebookManager()

    with patch("jupyter_mcp_server.extensions.get_extension_manager", return_value=ext_mgr):
        await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_A,
        )
        reply = await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=KERNEL_A,
        )

    assert "already connected" in reply
    assert KERNEL_A in reply
    assert "not applied" not in reply


class LocalContents:
    async def get(self, path, content=True, **kwargs):
        return {"content": [{"name": NB_PATH}]}


class LocalKernelManager:
    def get_kernel(self, kernel_id):
        return object() if kernel_id in (KERNEL_A, KERNEL_B) else None


class LocalSessionManager:
    def __init__(self):
        self.created: list[dict] = []

    async def list_sessions(self):
        return []

    async def create_session(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "local-session-created"}


@pytest.mark.asyncio
async def test_switch_kernel_on_current_notebook_jupyter_server():
    """JUPYTER_SERVER mode also switches an already-connected notebook to a different local kernel."""
    notebook_manager = NotebookManager()
    session_manager = LocalSessionManager()

    first = await UseNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LocalContents(),
        kernel_manager=LocalKernelManager(),
        session_manager=session_manager,
        notebook_manager=notebook_manager,
        notebook_name="demo",
        notebook_path=NB_PATH,
        use_mode="connect",
        kernel_id=KERNEL_A,
    )
    assert notebook_manager.get_code_sandbox_id("demo") == KERNEL_A
    assert f"Connected to kernel '{KERNEL_A}'" in first

    switched = await UseNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LocalContents(),
        kernel_manager=LocalKernelManager(),
        session_manager=session_manager,
        notebook_manager=notebook_manager,
        notebook_name="demo",
        notebook_path=NB_PATH,
        use_mode="connect",
        kernel_id=KERNEL_B,
    )
    assert f"Switched notebook 'demo' to kernel '{KERNEL_B}'" in switched
    assert notebook_manager.get_code_sandbox_id("demo") == KERNEL_B
