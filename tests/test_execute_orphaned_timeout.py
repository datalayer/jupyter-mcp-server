# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for the timeout path abandoning its background execution.

asyncio.Task.cancel() on a task wrapping asyncio.to_thread() cannot stop the
underlying OS thread: notebook.execute_cell() keeps running (and mutating the
shared notebook/kernel state) after a timeout has already been raised back to
the caller. is_kernel_busy() must reflect that so a subsequent call waits for
the orphaned execution instead of starting a second one against the same
kernel/notebook connection.
"""

import asyncio
import contextlib
import time

import pytest

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool
from jupyter_mcp_server.utils import (
    execute_cell_with_forced_sync,
    is_kernel_busy,
    wait_for_kernel_idle,
)


class FakeKernel:
    """Minimal stand-in covering the surface the execution paths use."""

    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


class FakeNotebook:
    """Single-cell notebook whose execute_cell runs a caller-supplied callable."""

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
    def __init__(self, notebook):
        self._notebook = notebook

    def get_current_notebook(self):
        return "default"

    def get_kernel_id(self, notebook_name):
        return "kernel-1"

    @contextlib.asynccontextmanager
    async def _connection(self):
        yield self._notebook

    def get_current_connection(self):
        return self._connection()


async def _run_stream(cell, execute_impl, timeout_seconds, kernel):
    manager = FakeNotebookManager(FakeNotebook(cell, execute_impl))
    return await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=None,
        contents_manager=None,
        kernel_manager=None,
        kernel_spec_manager=None,
        notebook_manager=manager,
        serverapp=None,
        cell_index=0,
        timeout_seconds=timeout_seconds,
        stream=True,
        progress_interval=1,
        ensure_kernel_alive_fn=lambda: kernel,
    )


@pytest.mark.asyncio
async def test_streaming_timeout_leaves_kernel_marked_busy_until_thread_finishes():
    """Regression for the timeout path abandoning its background thread with no
    way for anyone to see it is still running."""
    cell = {"source": "time.sleep(60)", "outputs": []}
    kernel = FakeKernel()

    await _run_stream(cell, lambda: time.sleep(0.3), timeout_seconds=0, kernel=kernel)

    # The tool already returned its [TIMEOUT ...] result, but the fake
    # execute_cell is still asleep in its background thread.
    assert is_kernel_busy(kernel) is True

    await asyncio.sleep(0.5)

    assert is_kernel_busy(kernel) is False


@pytest.mark.asyncio
async def test_wait_for_kernel_idle_blocks_until_orphaned_stream_task_finishes():
    """The guard every execute_cell/execute_code call makes before starting a
    new execution must actually wait for a prior timed-out one to finish,
    not read a kernel object that never reports busy."""
    cell = {"source": "time.sleep(60)", "outputs": []}
    kernel = FakeKernel()

    await _run_stream(cell, lambda: time.sleep(0.3), timeout_seconds=0, kernel=kernel)

    start = time.time()
    await wait_for_kernel_idle(kernel, max_wait_seconds=5)
    elapsed = time.time() - start

    assert elapsed >= 0.3
    assert is_kernel_busy(kernel) is False


@pytest.mark.asyncio
async def test_forced_sync_timeout_leaves_kernel_marked_busy_until_thread_finishes():
    """Same defect, non-streaming path (execute_cell_with_forced_sync)."""
    cell = {"source": "time.sleep(60)", "outputs": []}
    notebook = FakeNotebook(cell, lambda: time.sleep(0.3))
    kernel = FakeKernel()

    with pytest.raises(asyncio.TimeoutError):
        await execute_cell_with_forced_sync(notebook, 0, kernel, timeout_seconds=0)

    assert is_kernel_busy(kernel) is True

    await asyncio.sleep(0.5)

    assert is_kernel_busy(kernel) is False
