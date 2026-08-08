# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for long-running cell MCP progress keepalive (issue #298).

MCP clients often idle-timeout around a few minutes when a tool call is silent.
Raising ``--execution-timeout`` alone does not emit protocol traffic. These
tests assert that execute_cell (stream and non-stream) and execute_code invoke
the progress callback while a long cell is still running, and that a timed-out
stream path snapshots notebook outputs that land during the short settle window.
"""

import contextlib
import time

import pytest

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool
from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool
from jupyter_mcp_server.utils import execute_cell_with_forced_sync


class FakeKernel:
    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True

    def execute(self, code):
        time.sleep(2.2)
        return {"outputs": [{"output_type": "stream", "name": "stdout", "text": "done\n"}]}


class FakeNotebook:
    def __init__(self, cell, execute_impl):
        self._cell = cell
        self._execute_impl = execute_impl

    def __len__(self):
        return 1

    def __getitem__(self, index):
        return self._cell

    def execute_cell(self, cell_index, kernel):
        return self._execute_impl()


class FakeNotebookManager:
    def __init__(self, notebook, kernel=None):
        self._notebook = notebook
        self._kernel = kernel

    def get_current_notebook(self):
        return "default"

    def get_kernel_id(self, notebook_name):
        return "kernel-1"

    def get_kernel(self, notebook_name):
        return self._kernel

    @contextlib.asynccontextmanager
    async def _connection(self):
        yield self._notebook

    def get_current_connection(self):
        return self._connection()


class ProgressRecorder:
    def __init__(self):
        self.events = []

    async def __call__(self, *, elapsed, timeout_seconds, output_count=0, message=None):
        self.events.append(
            {
                "elapsed": elapsed,
                "timeout_seconds": timeout_seconds,
                "output_count": output_count,
                "message": message,
            }
        )


@pytest.mark.asyncio
async def test_stream_path_emits_progress_callback_during_long_cell():
    """Long streaming execute_cell must call progress_callback before completion."""
    cell = {"source": "time.sleep(3)", "outputs": []}
    kernel = FakeKernel()
    progress = ProgressRecorder()

    def execute_impl():
        time.sleep(2.2)
        cell["outputs"] = [
            {"output_type": "stream", "name": "stdout", "text": "hello\n"}
        ]

    manager = FakeNotebookManager(FakeNotebook(cell, execute_impl))
    result = await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=manager,
        cell_index=0,
        timeout_seconds=30,
        stream=True,
        progress_interval=1,
        ensure_kernel_alive_fn=lambda: kernel,
        progress_callback=progress,
    )

    assert progress.events, "expected at least one MCP progress keepalive event"
    assert all(event["elapsed"] > 0 for event in progress.events)
    assert any("[COMPLETED" in entry for entry in result if isinstance(entry, str))
    assert any("[PROGRESS:" in entry for entry in result if isinstance(entry, str))


@pytest.mark.asyncio
async def test_forced_sync_path_emits_progress_callback_during_long_cell():
    """Non-stream execute_cell (forced sync) must also emit keepalive progress."""
    cell = {"source": "time.sleep(3)", "outputs": []}
    notebook = FakeNotebook(cell, lambda: time.sleep(2.2))
    kernel = FakeKernel()
    progress = ProgressRecorder()

    await execute_cell_with_forced_sync(
        notebook,
        0,
        kernel,
        timeout_seconds=30,
        progress_callback=progress,
        progress_interval=1,
    )

    assert progress.events, "expected progress keepalive on the non-stream path"
    assert progress.events[0]["timeout_seconds"] == 30


@pytest.mark.asyncio
async def test_timeout_settle_includes_late_notebook_output_in_stream_result():
    """After timeout, settle briefly so outputs that land in the notebook are
    included in the tool response instead of appearing only as stray notebook
    writes after the client already timed out.

    timeout_seconds=0 must fire on the first monitor poll even when elapsed is
    still 0.0 (Windows time.time() coarse ticks used to miss ``elapsed > 0``,
    sleep a full second, and let a short background cell finish as COMPLETED).
    """
    cell = {"source": "time.sleep(60)", "outputs": []}
    kernel = FakeKernel()

    def execute_impl():
        # Land an output shortly after the tool hits timeout_seconds=0.
        # Must finish within TIMEOUT_OUTPUT_SETTLE_SECONDS (~1s).
        time.sleep(0.3)
        cell["outputs"] = [
            {"output_type": "stream", "name": "stdout", "text": "late-output\n"}
        ]

    manager = FakeNotebookManager(FakeNotebook(cell, execute_impl))
    result = await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=manager,
        cell_index=0,
        timeout_seconds=0,
        stream=True,
        progress_interval=1,
        ensure_kernel_alive_fn=lambda: kernel,
    )

    assert any("[TIMEOUT at" in entry for entry in result if isinstance(entry, str))
    assert any(
        isinstance(entry, str) and "late-output" in entry for entry in result
    ), f"expected settled notebook output in tool result, got {result!r}"
    assert cell["outputs"], "notebook cell should still hold the late output"


@pytest.mark.asyncio
async def test_immediate_timeout_with_frozen_perf_counter(monkeypatch):
    """Regression: timeout_seconds=0 must interrupt even if the elapsed clock
    never advances (same value returned twice), which is how Windows coarse
    time.time() made the settle test flake on CI (3.10)."""
    cell = {"source": "time.sleep(60)", "outputs": []}
    kernel = FakeKernel()
    frozen = {"t": 1000.0}

    def frozen_perf_counter():
        return frozen["t"]

    monkeypatch.setattr(time, "perf_counter", frozen_perf_counter)

    def execute_impl():
        time.sleep(0.3)
        cell["outputs"] = [
            {"output_type": "stream", "name": "stdout", "text": "late-output\n"}
        ]

    manager = FakeNotebookManager(FakeNotebook(cell, execute_impl))
    result = await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=manager,
        cell_index=0,
        timeout_seconds=0,
        stream=True,
        progress_interval=1,
        ensure_kernel_alive_fn=lambda: kernel,
    )

    assert any("[TIMEOUT at" in entry for entry in result if isinstance(entry, str)), (
        f"expected TIMEOUT with frozen clock, got {result!r}"
    )
    assert any(
        isinstance(entry, str) and "late-output" in entry for entry in result
    ), f"expected settled notebook output in tool result, got {result!r}"


@pytest.mark.asyncio
async def test_execute_code_emits_progress_callback_during_long_run():
    """execute_code sibling path must emit keepalive progress too."""
    kernel = FakeKernel()
    progress = ProgressRecorder()
    manager = FakeNotebookManager(FakeNotebook({"source": "", "outputs": []}, lambda: None), kernel=kernel)

    async def wait_idle(kernel, max_wait_seconds=30):
        return None

    result = await ExecuteCodeTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=manager,
        code="import time; time.sleep(2)",
        timeout=30,
        ensure_kernel_alive_fn=lambda: kernel,
        wait_for_kernel_idle_fn=wait_idle,
        safe_extract_outputs_fn=lambda outputs: [o.get("text", "") for o in outputs],
        progress_callback=progress,
        progress_interval=1,
    )

    assert progress.events, "expected progress keepalive from execute_code"
    assert any("done" in entry for entry in result if isinstance(entry, str))
