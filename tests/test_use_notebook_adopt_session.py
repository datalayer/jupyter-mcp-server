# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""``kernel.adopt-session`` reuses a notebook's existing Jupyter kernel (#464)."""

from types import SimpleNamespace

import pytest

from jupyter_mcp_server.capabilities import (
    CAPABILITIES_ENV,
    KERNEL_ADOPT_SESSION,
    get_capabilities,
    reset_capabilities,
)
from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

SANDBOX_URL = "http://sandbox.example"
SESSION_KERNEL = "kernel-from-session"
SESSION = {"path": "nb.ipynb", "kernel": {"id": SESSION_KERNEL}}
MCP_SESSION = SimpleNamespace(path=SESSION["path"], kernel=SimpleNamespace(id=SESSION_KERNEL))


class FakeSessions:
    def __init__(self, sessions):
        self._sessions = sessions
        self.calls = 0

    def list_sessions(self):
        self.calls += 1
        return self._sessions


class FakeServerClient:
    def __init__(self, sessions):
        self.contents = SimpleNamespace(
            list_directory=lambda path: [SimpleNamespace(name="nb.ipynb")],
            get=lambda path: {"content": {"cells": []}},
        )
        # A live session implies a live kernel; the kernel list mirrors the
        # sessions so the two answers cannot contradict each other.
        self.kernels = SimpleNamespace(
            list_kernels=lambda: [
                SimpleNamespace(id=session.kernel.id) for session in sessions
            ]
        )
        self.sessions = FakeSessions(sessions)

    def get_status(self):
        return {}


class LocalContents:
    async def get(self, path, content=True, **kwargs):
        return {"content": [{"name": "nb.ipynb"}]}


class LocalKernelManager:
    def __init__(self):
        self.started = []

    def __contains__(self, kernel_id):
        return kernel_id == SESSION_KERNEL

    async def start_kernel(self, path=None):
        self.started.append(path)
        return "new-kernel"

    def get_kernel(self, kernel_id):
        return object()

    def get_connection_info(self, kernel_id):
        return {"shell_port": 1}


class LocalSessionManager:
    def __init__(self, sessions):
        self._sessions = sessions
        self.calls = 0
        self.created = []

    async def list_sessions(self):
        self.calls += 1
        return self._sessions

    async def create_session(self, path=None, kernel_id=None, **kwargs):
        self.created.append(kernel_id)
        return {"id": "created-session"}


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.delenv(CAPABILITIES_ENV, raising=False)
    reset_capabilities()
    reset_config()
    yield
    reset_capabilities()
    reset_config()


@pytest.fixture
def sandbox_factory(monkeypatch):
    seen = {}

    def fake_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            id=kwargs.get("kernel_id") or "new-kernel", is_alive=lambda: True
        )

    monkeypatch.setattr(
        "jupyter_mcp_server.sandbox_client.create_jupyter_sandbox_client", fake_client
    )
    monkeypatch.setattr("jupyter_mcp_server.watchers.watchers.watch", lambda name, manager: False)
    monkeypatch.setattr(
        "jupyter_mcp_server.extensions.get_extension_manager",
        lambda: SimpleNamespace(create_code_sandbox=lambda config, logger: None),
    )
    monkeypatch.setattr(
        "jupyter_mcp_server.server_context.ServerContext.get_instance",
        staticmethod(
            lambda: SimpleNamespace(
                document_server_client=FakeServerClient([]),
                document_auth_headers={},
                code_sandbox_auth_headers={},
            )
        ),
    )
    return seen


async def _use_mcp(client):
    return await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=client,
        notebook_manager=NotebookManager(),
        notebook_name="demo",
        notebook_path="nb.ipynb",
        use_mode="connect",
        code_sandbox_url=SANDBOX_URL,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "start_new", "sessions", "calls", "kernel_id", "reply"),
    [
        (True, False, [MCP_SESSION], 1, SESSION_KERNEL, "Adopted kernel"),
        # Adoption off, a kernel is running, and nothing names one: refuse
        # rather than add a second kernel (#478).
        (False, False, [MCP_SESSION], 1, None, "Cannot open"),
        (True, True, [], 1, None, "Connected to kernel 'new-kernel'"),
    ],
)
async def test_mcp_server_session_adoption_paths(
    sandbox_factory, enabled, start_new, sessions, calls, kernel_id, reply
):
    if enabled:
        get_capabilities().set(KERNEL_ADOPT_SESSION, True, source="cli")
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=start_new)

    answer = await _use_mcp(FakeServerClient(sessions))

    assert sandbox_factory.get("kernel_id") == kernel_id
    assert reply in answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "sessions", "calls", "started", "created", "kernel_id", "reply"),
    [
        (True, [SESSION], 1, [], [], SESSION_KERNEL, "Adopted kernel"),
        # Adoption off, a kernel is running, nothing names it: refuse.
        (False, [SESSION], 1, [], [], None, "Cannot open"),
        (True, [], 1, ["nb.ipynb"], ["new-kernel"], "new-kernel", None),
    ],
)
async def test_jupyter_server_session_adoption_paths(
    enabled, sessions, calls, started, created, kernel_id, reply
):
    if enabled:
        get_capabilities().set(KERNEL_ADOPT_SESSION, True, source="cli")
    kernels = LocalKernelManager()
    session_manager = LocalSessionManager(sessions)
    notebook_manager = NotebookManager()

    answer = await UseNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LocalContents(),
        kernel_manager=kernels,
        session_manager=session_manager,
        notebook_manager=notebook_manager,
        notebook_name="demo",
        notebook_path="nb.ipynb",
        use_mode="connect",
    )

    assert session_manager.calls == calls
    assert kernels.started == started
    assert session_manager.created == created
    assert notebook_manager.get_code_sandbox_id("demo") == kernel_id
    if reply:
        assert reply in answer
