# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The backend ``use_notebook`` selects, or deliberately does not select.

``use_notebook`` follows the context the caller already established:

* an active ``use_sandbox`` selection wins;
* otherwise a live session for the notebook is adopted as part of the call and
  the reply says that ``use_sandbox`` was triggered;
* with neither, no kernel is created;
* an explicit ``kernel_id`` is verified and gets a session when one is missing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import NEW_KERNEL_ID, UseNotebookTool

SANDBOX_URL = "http://sandbox.example"
EXISTING_KERNEL = "kernel-existing"
SESSION_KERNEL = "kernel-from-session"
NB_PATH = "nb.ipynb"


class FakeContents:
    @staticmethod
    def list_directory(path):
        return [SimpleNamespace(name=NB_PATH)]

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
    def __init__(self, active=None):
        self.active = active
        self.created_with: list[str | None] = []
        self.created_new = 0

    def get_active_code_sandbox(self, config, logger):
        return self.active

    def create_code_sandbox(self, config, logger):
        self.created_with.append(config.code_sandbox_id)
        return SimpleNamespace(id=config.code_sandbox_id or "kernel-new")

    def create_new_code_sandbox(self, config, logger):
        self.created_new += 1
        return SimpleNamespace(id="kernel-new")


def _session(path, kernel_id):
    return SimpleNamespace(path=path, kernel=SimpleNamespace(id=kernel_id))


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr("jupyter_mcp_server.watchers.watchers.watch", lambda name, manager: False)
    reset_config()
    yield
    reset_config()


async def _use(client, active_sandbox, *, kernel_id=None):
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=False)
    extension_manager = FakeExtensionManager(active=active_sandbox)
    notebook_manager = NotebookManager()
    with patch(
        "jupyter_mcp_server.extensions.get_extension_manager",
        return_value=extension_manager,
    ):
        reply = await UseNotebookTool().execute(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=client,
            notebook_manager=notebook_manager,
            notebook_name="demo",
            notebook_path=NB_PATH,
            use_mode="connect",
            code_sandbox_url=SANDBOX_URL,
            kernel_id=kernel_id,
        )
    return reply, extension_manager, notebook_manager


@pytest.mark.asyncio
async def test_active_use_sandbox_is_the_notebook_backend():
    """A sandbox selected before opening the notebook must be the one used."""
    active = SimpleNamespace(id="sandbox-selected", is_alive=lambda: True)
    reply, extension_manager, notebook_manager = await _use(FakeServerClient(), active)

    assert "active code sandbox" in reply
    assert "use_sandbox" in reply
    assert "sandbox-selected" in reply
    assert extension_manager.created_with == []
    assert notebook_manager.get_code_sandbox("demo") is active


@pytest.mark.asyncio
async def test_existing_session_triggers_use_sandbox_and_says_so():
    """The notebook's live session is the backend, not a second kernel."""
    session = _session(NB_PATH, SESSION_KERNEL)
    client = FakeServerClient(kernels=[SESSION_KERNEL], sessions=[session])
    reply, extension_manager, notebook_manager = await _use(client, None)

    assert extension_manager.created_with == [SESSION_KERNEL]
    assert notebook_manager.get_code_sandbox_id("demo") == SESSION_KERNEL
    assert "Triggered 'use_sandbox'" in reply
    assert SESSION_KERNEL in reply
    assert client.sessions.created == [], "an existing session must not be duplicated"


@pytest.mark.asyncio
async def test_no_sandbox_and_no_session_does_not_create_a_kernel():
    client = FakeServerClient()
    reply, extension_manager, notebook_manager = await _use(client, None)

    assert extension_manager.created_with == []
    assert notebook_manager.get_code_sandbox("demo") is None
    assert client.sessions.created == []
    assert "no kernel was created" in reply


@pytest.mark.asyncio
async def test_explicit_kernel_gets_a_session_when_missing():
    client = FakeServerClient(kernels=[EXISTING_KERNEL])
    reply, extension_manager, notebook_manager = await _use(client, None, kernel_id=EXISTING_KERNEL)

    assert extension_manager.created_with == [EXISTING_KERNEL]
    assert notebook_manager.get_code_sandbox_id("demo") == EXISTING_KERNEL
    assert client.sessions.created == [
        {
            "path": NB_PATH,
            "kernel": {"id": EXISTING_KERNEL},
            "session_type": "notebook",
            "name": NB_PATH,
        }
    ]
    assert "Created Jupyter session" in reply


@pytest.mark.asyncio
async def test_new_kernel_request_bypasses_the_active_sandbox():
    active = SimpleNamespace(id="sandbox-selected", is_alive=lambda: True)
    reply, extension_manager, notebook_manager = await _use(
        FakeServerClient(), active, kernel_id=NEW_KERNEL_ID
    )

    assert extension_manager.created_new == 1
    assert extension_manager.created_with == []
    assert notebook_manager.get_code_sandbox_id("demo") == "kernel-new"
    assert "isolated kernel" in reply


@pytest.mark.asyncio
async def test_explicit_kernel_that_is_not_alive_is_refused():
    client = FakeServerClient(kernels=[])
    reply, extension_manager, _notebook_manager = await _use(client, None, kernel_id="missing")

    assert "not found" in reply
    assert extension_manager.created_with == []
    assert client.sessions.created == []


#### JUPYTER_SERVER explicit kernel path #####################################


class LocalContents:
    async def get(self, path, content=True, **kwargs):
        return {"content": [{"name": NB_PATH}]}


class LocalKernelManager:
    def get_kernel(self, kernel_id):
        return object() if kernel_id == EXISTING_KERNEL else None


class LocalSessionManager:
    def __init__(self, sessions=()):
        self._sessions = list(sessions)
        self.created: list[dict] = []

    async def list_sessions(self):
        return self._sessions

    async def create_session(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "local-session-created"}


@pytest.mark.asyncio
async def test_jupyter_server_explicit_kernel_creates_session_when_missing():
    session_manager = LocalSessionManager()
    reply = await UseNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LocalContents(),
        kernel_manager=LocalKernelManager(),
        session_manager=session_manager,
        notebook_manager=NotebookManager(),
        notebook_name="demo",
        notebook_path=NB_PATH,
        use_mode="connect",
        kernel_id=EXISTING_KERNEL,
    )

    assert session_manager.created == [
        {
            "path": NB_PATH,
            "kernel_id": EXISTING_KERNEL,
            "type": "notebook",
            "name": NB_PATH,
        }
    ]
    assert "Created Jupyter session" in reply
