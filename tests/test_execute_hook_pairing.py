# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""BEFORE_EXECUTE / AFTER_EXECUTE pairing on the JUPYTER_SERVER-mode exits.

A handler stashes per-execution state in the context BEFORE_EXECUTE returns and
releases it on AFTER_EXECUTE (OTelHookHandler ends its span there, and
SimpleSpanProcessor exports on end), so every exit past the BEFORE fire owes
exactly one AFTER, error paths included.
"""

import asyncio
import json

import pytest
import zmq
import zmq.asyncio

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.otel_hook import create_otel_handler
from jupyter_mcp_server.utils import (
    MissingKernelError,
    execute_code_local,
    execute_via_execution_stack,
)


class RecordingHandler:
    """Records every event, stashing state in the context like OTelHookHandler."""

    propagate_errors = False

    def __init__(self):
        self.events: list[tuple[HookEvent, dict]] = []

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        if event == HookEvent.BEFORE_EXECUTE:
            kwargs["context"]["_recorded_execution"] = kwargs.get("code")
        self.events.append((event, kwargs))

    def of_type(self, event: HookEvent) -> list[dict]:
        return [kwargs for recorded, kwargs in self.events if recorded == event]


@pytest.fixture(autouse=True)
def reset_registry():
    HookRegistry.reset()
    yield
    HookRegistry.reset()


@pytest.fixture
def handler():
    recorder = RecordingHandler()
    HookRegistry.get_instance().register(recorder)
    return recorder


def assert_paired(handler: RecordingHandler) -> dict:
    """Assert exactly one BEFORE_EXECUTE, one AFTER_EXECUTE, one shared context."""
    before = handler.of_type(HookEvent.BEFORE_EXECUTE)
    after = handler.of_type(HookEvent.AFTER_EXECUTE)
    assert len(before) == 1, f"expected 1 BEFORE_EXECUTE, got {len(before)}"
    assert len(after) == 1, f"expected 1 AFTER_EXECUTE, got {len(after)}"
    assert after[0]["context"] is before[0]["context"], (
        "AFTER_EXECUTE must carry the context BEFORE_EXECUTE returned, so a "
        "handler can release the state it stashed there"
    )
    assert "_recorded_execution" in after[0]["context"]
    return after[0]


# --------------------------------------------------------------------------
# execute_via_execution_stack (jupyter-server-nbmodel installed)
# --------------------------------------------------------------------------


class _ExecutionStack:
    """Stand-in for jupyter_server_nbmodel's ExecutionStack. *results* is what
    get() returns per poll; *get_error* is raised from get() instead."""

    def __init__(self, results=(), get_error=None):
        self._results = iter(results)
        self._get_error = get_error
        self.cancelled: list[str] = []

    def put(self, kernel_id, code, metadata):
        return "request-id"

    def get(self, kernel_id, request_id):
        if self._get_error is not None:
            raise self._get_error
        return next(self._results, None)

    def cancel(self, kernel_id):
        self.cancelled.append(kernel_id)


class _Extension:
    def __init__(self, execution_stack):
        self._Extension__execution_stack = execution_stack


class _ExtensionManager:
    def __init__(self, extension):
        apps = {extension} if extension is not None else set()
        self.extension_apps = {"jupyter_server_nbmodel": apps}


class _ServerApp:
    def __init__(self, execution_stack=None, kernel_manager=None):
        extension = _Extension(execution_stack) if execution_stack is not None else None
        self.extension_manager = _ExtensionManager(extension)
        self.kernel_manager = kernel_manager


@pytest.mark.asyncio
async def test_success_fires_a_paired_after_execute(handler):
    """Control: the path that already worked, measured with the same harness."""
    stack = _ExecutionStack(
        results=[
            {
                "pending": False,
                "request_status": "complete",
                "status": "ok",
                "execution_count": 1,
                "outputs": json.dumps(
                    [{"output_type": "stream", "name": "stdout", "text": "hi\n"}]
                ),
            }
        ]
    )

    await execute_via_execution_stack(
        serverapp=_ServerApp(stack), kernel_id="kernel-1", code="print('hi')", poll_interval=0
    )

    assert assert_paired(handler)["error"] is None


@pytest.mark.asyncio
async def test_unexpected_input_request_fires_after_execute(handler):
    stack = _ExecutionStack(results=[{"pending": False, "input_request": {"prompt": "?"}}])

    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(stack), kernel_id="kernel-1", code="input()", poll_interval=0
    )

    assert outputs == ["[ERROR: Unexpected input request]"]
    assert assert_paired(handler)["error"] is not None


@pytest.mark.asyncio
async def test_unparseable_outputs_fire_after_execute(handler):
    stack = _ExecutionStack(
        results=[{"pending": False, "request_status": "complete", "outputs": "{not json"}]
    )

    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(stack), kernel_id="kernel-1", code="print(1)", poll_interval=0
    )

    assert outputs == ["[ERROR: Invalid output format]"]
    after = assert_paired(handler)
    assert isinstance(after["error"], json.JSONDecodeError)


@pytest.mark.asyncio
async def test_timeout_fires_after_execute(handler):
    """The path observability most needs: a cell that never finishes."""
    stack = _ExecutionStack(results=[])  # always pending

    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(stack),
        kernel_id="kernel-1",
        code="while True: pass",
        timeout=0,
        poll_interval=0,
    )

    assert any("timed out" in str(output) for output in outputs)
    after = assert_paired(handler)
    assert isinstance(after["error"], TimeoutError)
    assert stack.cancelled == ["kernel-1"]


@pytest.mark.asyncio
async def test_user_cancellation_fires_after_execute(handler):
    """An MCP user-cancel unwinds through the same cleanup block."""
    stack = _ExecutionStack(results=[])

    task = asyncio.create_task(
        execute_via_execution_stack(
            serverapp=_ServerApp(stack),
            kernel_id="kernel-1",
            code="while True: pass",
            timeout=300,
            poll_interval=0.01,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    after = assert_paired(handler)
    assert isinstance(after["error"], asyncio.CancelledError)
    assert stack.cancelled == ["kernel-1"]


@pytest.mark.asyncio
async def test_unexpected_error_after_submission_fires_after_execute(handler):
    stack = _ExecutionStack(get_error=ValueError("stack blew up"))

    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(stack), kernel_id="kernel-1", code="print(1)", poll_interval=0
    )

    assert outputs == ["[ERROR: stack blew up]"]
    after = assert_paired(handler)
    assert isinstance(after["error"], ValueError)


@pytest.mark.asyncio
async def test_missing_kernel_fires_after_execute_before_it_propagates(handler):
    """The one request-level failure that leaves as an exception still owes its AFTER."""
    stack = _ExecutionStack(
        results=[
            {
                "error": "HTTP 404: Not Found (Kernel does not exist: kernel-1)",
                "pending": False,
                "request_status": "complete",
            }
        ]
    )

    with pytest.raises(MissingKernelError):
        await execute_via_execution_stack(
            serverapp=_ServerApp(stack), kernel_id="kernel-1", code="print(1)", poll_interval=0
        )

    after = assert_paired(handler)
    assert isinstance(after["error"], MissingKernelError)


@pytest.mark.asyncio
async def test_failure_before_the_hook_fires_nothing(handler):
    """No extension, so BEFORE_EXECUTE never fires and no AFTER is owed."""
    outputs = await execute_via_execution_stack(
        serverapp=_ServerApp(execution_stack=None), kernel_id="kernel-1", code="print(1)"
    )

    assert outputs == ["[ERROR: jupyter_server_nbmodel extension not found. Please install it.]"]
    assert handler.events == []


# --------------------------------------------------------------------------
# execute_code_local (no jupyter-server-nbmodel; raw kernel client)
# --------------------------------------------------------------------------


class _Channel:
    """Channel over a real, never written to, zmq socket, so the poller
    registration and polling under test run for real."""

    def __init__(self, socket, send_error=None):
        self.socket = socket
        self._send_error = send_error

    def send(self, msg):
        if self._send_error is not None:
            raise self._send_error

    def get_msg(self, timeout=0):
        return None


class _Session:
    def msg(self, msg_type, content):
        return {"header": {"msg_id": "msg-1"}, "content": content}


class _KernelClient:
    def __init__(self, context, send_error=None):
        self.channels_running = True
        self.shell_channel = _Channel(context.socket(zmq.PULL), send_error=send_error)
        self.iopub_channel = _Channel(context.socket(zmq.PULL))

    def start_channels(self):
        self.channels_running = True

    def stop_channels(self):
        self.channels_running = False

    def close(self):
        self.shell_channel.socket.close()
        self.iopub_channel.socket.close()


class _Kernel:
    def __init__(self, client):
        self.session = _Session()
        self._client = client

    def client(self):
        return self._client


class _PinnedSuperclass:
    def __init__(self, kernel):
        self._kernel = kernel

    def get_kernel(self, kernel_manager, kernel_id):
        return self._kernel


class _KernelManager:
    def __init__(self, kernel):
        self.pinned_superclass = _PinnedSuperclass(kernel)


@pytest.mark.asyncio
async def test_local_timeout_fires_after_execute(handler):
    context = zmq.asyncio.Context()
    client = _KernelClient(context)
    try:
        outputs = await execute_code_local(
            serverapp=_ServerApp(kernel_manager=_KernelManager(_Kernel(client))),
            notebook_path="notebook.ipynb",
            code="while True: pass",
            kernel_id="kernel-1",
            timeout=1,
        )

        assert outputs == ["[TIMEOUT ERROR: Code execution exceeded 1 seconds]"]
        after = assert_paired(handler)
        assert isinstance(after["error"], asyncio.TimeoutError)
    finally:
        client.close()
        context.term()


@pytest.mark.asyncio
async def test_local_unexpected_error_fires_after_execute(handler):
    context = zmq.asyncio.Context()
    client = _KernelClient(context, send_error=RuntimeError("shell channel is dead"))
    try:
        outputs = await execute_code_local(
            serverapp=_ServerApp(kernel_manager=_KernelManager(_Kernel(client))),
            notebook_path="notebook.ipynb",
            code="print(1)",
            kernel_id="kernel-1",
            timeout=5,
        )

        assert outputs == ["[ERROR: shell channel is dead]"]
        after = assert_paired(handler)
        assert isinstance(after["error"], RuntimeError)
    finally:
        client.close()
        context.term()


@pytest.mark.asyncio
async def test_local_user_cancellation_fires_after_execute(handler):
    """An MCP user-cancel unwinds out of the poll, on this path too."""
    context = zmq.asyncio.Context()
    client = _KernelClient(context)
    try:
        task = asyncio.create_task(
            execute_code_local(
                serverapp=_ServerApp(kernel_manager=_KernelManager(_Kernel(client))),
                notebook_path="notebook.ipynb",
                code="while True: pass",
                kernel_id="kernel-1",
                timeout=300,
            )
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        after = assert_paired(handler)
        assert isinstance(after["error"], asyncio.CancelledError)
    finally:
        client.close()
        context.term()


# --------------------------------------------------------------------------
# What an unpaired BEFORE_EXECUTE costs a real handler
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timed_out_execution_exports_an_otel_span(tmp_path):
    """An unpaired execution is missing from the span file entirely."""
    spans_file = tmp_path / "spans.jsonl"
    HookRegistry.get_instance().register(create_otel_handler(file_path=spans_file))

    await execute_via_execution_stack(
        serverapp=_ServerApp(_ExecutionStack(results=[])),
        kernel_id="kernel-1",
        code="while True: pass",
        timeout=0,
        poll_interval=0,
    )

    spans = [json.loads(line) for line in spans_file.read_text().splitlines() if line.strip()]
    assert len(spans) == 1, f"expected the timed-out execution to be exported, got {spans}"
    assert spans[0]["name"] == "execute"
    assert spans[0]["attributes"]["error"] is True
    assert spans[0]["end_time"] is not None
