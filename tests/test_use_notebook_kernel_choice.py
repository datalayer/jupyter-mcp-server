# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""`use_notebook` refuses to add a rival kernel, and starts one on request.

Owning a kernel is a decision. While the Jupyter server already runs kernels
or sessions this server did not start, opening a notebook silently would
either hijack the person's session or add a second kernel nobody watches
(#478). The caller chooses: name an existing kernel to share its state, or
ask for an isolated one with ``kernel_id=NEW``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jupyter_mcp_server.capabilities import (
    KERNEL_ADOPT_SESSION,
    get_capabilities,
    reset_capabilities,
)
from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import NEW_KERNEL_ID, UseNotebookTool

SANDBOX_URL = "http://sandbox.example"
LIVE_KERNEL = "live-kernel-1"
SESSION_KERNEL = "session-kernel-1"
NB_PATH = "nb.ipynb"


class FakeContents:
    def __init__(self, names=(NB_PATH,)):
        self._names = list(names)

    def list_directory(self, path):
        return [SimpleNamespace(name=name) for name in self._names]

    @staticmethod
    def get(path):
        return {"content": {"cells": []}}

    @staticmethod
    def create_notebook(path, content=None):
        return None


class FakeKernels:
    def __init__(self, ids):
        self._ids = list(ids)

    def list_kernels(self):
        return [SimpleNamespace(id=kernel_id) for kernel_id in self._ids]


class FakeSessions:
    def __init__(self, sessions):
        self._sessions = list(sessions)

    def list_sessions(self):
        return self._sessions


class FakeServerClient:
    def __init__(self, kernels=(), sessions=(), names=(NB_PATH,)):
        self.contents = FakeContents(names)
        self.kernels = FakeKernels(kernels)
        self.sessions = FakeSessions(sessions)

    def get_status(self):
        return {}


def _session(path, kernel_id):
    return SimpleNamespace(path=path, kernel=SimpleNamespace(id=kernel_id))


@pytest.fixture(autouse=True)
def sandbox(monkeypatch):
    """Capture the sandbox the tool asks for, and keep the network out."""
    seen: dict = {}

    def fake_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            id=kwargs.get("kernel_id") or "brand-new-kernel", is_alive=lambda: True
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
        staticmethod(lambda: SimpleNamespace(code_sandbox_auth_headers={})),
    )
    reset_config()
    reset_capabilities()
    yield seen
    reset_config()
    reset_capabilities()


def _use(client, *, kernel_id=None, start_new=False, notebook_manager=None, use_mode="connect"):
    set_config(code_sandbox_url=SANDBOX_URL, start_new_code_sandbox=start_new)
    return UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=client,
        notebook_manager=notebook_manager or NotebookManager(),
        notebook_name="demo",
        notebook_path=NB_PATH,
        use_mode=use_mode,
        code_sandbox_url=SANDBOX_URL,
        kernel_id=kernel_id,
    )


def _enable_adoption():
    get_capabilities().set(KERNEL_ADOPT_SESSION, True, source="cli")


@pytest.mark.asyncio
async def test_it_refuses_while_another_session_runs(sandbox):
    client = FakeServerClient(
        kernels=[LIVE_KERNEL], sessions=[_session("other.ipynb", LIVE_KERNEL)]
    )

    reply = await _use(client)

    assert "Cannot open" in reply
    assert LIVE_KERNEL in reply
    assert NEW_KERNEL_ID in reply
    assert sandbox == {}, "no sandbox may be built when the call is refused"


@pytest.mark.asyncio
async def test_a_running_session_kernel_is_named_in_the_refusal(sandbox):
    client = FakeServerClient(kernels=[], sessions=[_session(NB_PATH, SESSION_KERNEL)])

    reply = await _use(client)

    assert "Cannot open" in reply
    assert SESSION_KERNEL in reply
    assert sandbox == {}


@pytest.mark.asyncio
async def test_a_bare_kernel_is_not_a_session(sandbox):
    """A kernel nothing is attached to is not a person's work to protect.

    A long-lived Jupyter server accumulates them (an earlier agent, a
    finished test), and refusing on those made every open fail on a busy
    server without protecting anything.
    """
    reply = await _use(FakeServerClient(kernels=[LIVE_KERNEL]))

    assert "Cannot open" not in reply
    assert "A kernel starts on the first execution" in reply


@pytest.mark.asyncio
async def test_nothing_running_keeps_the_lazy_open(sandbox):
    reply = await _use(FakeServerClient(kernels=[]))

    assert "A kernel starts on the first execution" in reply
    assert sandbox == {}


@pytest.mark.asyncio
async def test_a_failed_probe_is_not_a_refusal(sandbox):
    """A client that cannot answer must not be read as "kernels are running"."""
    client = SimpleNamespace(contents=FakeContents(), get_status=lambda: {})

    reply = await _use(client)

    assert "A kernel starts on the first execution" in reply


@pytest.mark.asyncio
async def test_kernel_id_new_starts_an_isolated_kernel(sandbox):
    reply = await _use(FakeServerClient(kernels=[LIVE_KERNEL]), kernel_id=NEW_KERNEL_ID)

    assert "Cannot open" not in reply
    assert sandbox.get("kernel_id") is None, "a NEW request must not name an existing kernel"
    assert "isolated kernel" in reply


@pytest.mark.asyncio
async def test_kernel_id_new_wins_over_a_deferred_open(sandbox):
    """`--start-new-code-sandbox false` defers a bare open, not a NEW request."""
    reply = await _use(FakeServerClient(kernels=[LIVE_KERNEL]), kernel_id=NEW_KERNEL_ID)

    assert "isolated kernel" in reply
    assert sandbox.get("path") == NB_PATH


@pytest.mark.asyncio
async def test_naming_an_existing_kernel_attaches_to_it(sandbox):
    reply = await _use(FakeServerClient(kernels=[LIVE_KERNEL]), kernel_id=LIVE_KERNEL)

    assert sandbox.get("kernel_id") == LIVE_KERNEL
    assert f"Connected to kernel '{LIVE_KERNEL}'" in reply


@pytest.mark.asyncio
async def test_a_kernel_this_server_started_is_not_a_rival(sandbox):
    """The server's own kernels are what the notebooks it manages run on."""
    manager = NotebookManager()
    manager.add_notebook(
        "other", SimpleNamespace(id=LIVE_KERNEL), server_url="u", path="other.ipynb"
    )
    client = FakeServerClient(
        kernels=[LIVE_KERNEL], sessions=[_session("other.ipynb", LIVE_KERNEL)]
    )

    reply = await _use(client, notebook_manager=manager)

    assert "Cannot open" not in reply
    assert "A kernel starts on the first execution" in reply


@pytest.mark.asyncio
async def test_creating_a_notebook_is_an_explicit_choice(sandbox):
    """`mode='create'` names a new notebook; the kernel decision is already made."""
    client = FakeServerClient(
        kernels=[LIVE_KERNEL],
        sessions=[_session("other.ipynb", LIVE_KERNEL)],
        names=[],
    )

    reply = await _use(client, use_mode="create")

    assert "Cannot open" not in reply
    assert "A kernel starts on the first execution" in reply
    assert sandbox.get("kernel_id") is None


@pytest.mark.asyncio
async def test_adoption_still_wins_over_the_refusal(sandbox):
    _enable_adoption()
    client = FakeServerClient(
        kernels=[SESSION_KERNEL], sessions=[_session(NB_PATH, SESSION_KERNEL)]
    )

    reply = await _use(client)

    assert f"Adopted kernel '{SESSION_KERNEL}'" in reply
    assert sandbox.get("kernel_id") == SESSION_KERNEL


@pytest.mark.asyncio
async def test_adoption_does_not_rescue_a_foreign_kernel(sandbox):
    _enable_adoption()
    client = FakeServerClient(
        kernels=[LIVE_KERNEL], sessions=[_session("other.ipynb", LIVE_KERNEL)]
    )

    reply = await _use(client)

    assert "Cannot open" in reply
    assert sandbox == {}


#### JUPYTER_SERVER mode ####################################################


class LocalContents:
    async def get(self, path, content=True, **kwargs):
        return {"content": [{"name": NB_PATH}]}


class LocalKernelManager:
    def __init__(self, ids=()):
        self._ids = set(ids)
        self.started: list = []

    def list_kernels(self):
        return [{"id": kernel_id} for kernel_id in sorted(self._ids)]

    def __contains__(self, kernel_id):
        return kernel_id in self._ids

    async def start_kernel(self, path=None):
        self.started.append(path)
        return "local-new-kernel"

    def get_kernel(self, kernel_id):
        return object()

    def get_connection_info(self, kernel_id):
        return {"shell_port": 1}


class LocalSessionManager:
    def __init__(self, sessions=()):
        self._sessions = list(sessions)
        self.created: list = []

    async def list_sessions(self):
        return self._sessions

    async def create_session(self, path=None, kernel_id=None, **kwargs):
        self.created.append(kernel_id)
        return {"id": "session-created"}


async def _use_local(kernel_id=None, *, kernels=(), sessions=()):
    reset_config()
    kernel_manager = LocalKernelManager(kernels)
    session_manager = LocalSessionManager(sessions)
    reply = await UseNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=LocalContents(),
        kernel_manager=kernel_manager,
        session_manager=session_manager,
        notebook_manager=NotebookManager(),
        notebook_name="demo",
        notebook_path=NB_PATH,
        use_mode="connect",
        kernel_id=kernel_id,
    )
    return reply, kernel_manager, session_manager


@pytest.mark.asyncio
async def test_jupyter_server_refuses_while_a_kernel_runs():
    reply, kernel_manager, _ = await _use_local(
        kernels=[LIVE_KERNEL], sessions=[_session(NB_PATH, LIVE_KERNEL)]
    )

    assert "Cannot open" in reply
    assert kernel_manager.started == []


@pytest.mark.asyncio
async def test_jupyter_server_new_starts_a_local_kernel():
    reply, kernel_manager, session_manager = await _use_local(
        NEW_KERNEL_ID, kernels=[LIVE_KERNEL]
    )

    assert kernel_manager.started == [NB_PATH]
    assert session_manager.created == ["local-new-kernel"]
    assert "Cannot open" not in reply


@pytest.mark.asyncio
async def test_jupyter_server_opens_when_nothing_runs():
    reply, kernel_manager, _ = await _use_local()

    assert kernel_manager.started == [NB_PATH]
    assert "Connected to kernel 'local-new-kernel'" in reply
