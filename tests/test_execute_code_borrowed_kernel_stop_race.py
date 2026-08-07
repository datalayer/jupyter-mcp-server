# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression test for _execute_via_notebook_manager releasing a borrowed
kernel connection while its background execution is still in flight.

asyncio.Task.cancel() on a task wrapping asyncio.to_thread() cannot stop the
underlying OS thread (see track_pending_execution / test_execute_code_orphaned_timeout.py).
On a timeout, _execute_on_kernel can return before that background thread has
actually finished. The finally block in _execute_via_notebook_manager must not
stop the borrowed sandbox client while that thread is still using it; doing so
pulls the transport out from under a call still in progress.
"""

import asyncio
import threading
import time

import pytest

from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool

# Mirrors tests/test_execute_code_orphaned_timeout.py's _ORPHANED_TASK_SLEEP:
# long enough that the background thread is still running when the tool
# returns its timeout result.
_ORPHANED_TASK_SLEEP = 2.0


class FakeBorrowedKernel:
    """Minimal stand-in covering the surface a borrowed sandbox client needs."""

    def __init__(self, execute_impl):
        self.interrupted = False
        self._execute_impl = execute_impl
        self._finished = threading.Event()
        self.stop_calls = []
        self.stopped_while_task_pending = None

    def execute(self, code):
        try:
            return self._execute_impl()
        finally:
            self._finished.set()

    def interrupt(self):
        self.interrupted = True

    def stop(self, shutdown_kernel=False):
        self.stop_calls.append(shutdown_kernel)
        self.stopped_while_task_pending = not self._finished.is_set()


class FakeNotebookManager:
    """Reports a different current kernel so kernel_id below is borrowed."""

    def get_current_notebook(self):
        return "default"

    def get_kernel_id(self, notebook):
        return "current-kernel"


class BorrowedKernelExecuteCodeTool(ExecuteCodeTool):
    """Skips real kernel-id lookup and hands back the fake client directly."""

    def __init__(self, fake_kernel):
        self._fake_kernel = fake_kernel

    def _connect_to_kernel(self, kernel_id, server_client):
        return self._fake_kernel, None


async def _noop_wait_for_kernel_idle(kernel, max_wait_seconds=30):
    return None


@pytest.mark.asyncio
async def test_borrowed_kernel_not_stopped_while_execution_task_pending():
    """Regression: the finally block must not release a borrowed kernel
    connection synchronously if its background execute() thread is still
    running when the tool returns its timeout result."""
    kernel = FakeBorrowedKernel(lambda: time.sleep(_ORPHANED_TASK_SLEEP))

    result = await BorrowedKernelExecuteCodeTool(kernel)._execute_via_notebook_manager(
        notebook_manager=FakeNotebookManager(),
        code="time.sleep(60)",
        timeout=0,
        ensure_kernel_alive_fn=lambda: None,
        wait_for_kernel_idle_fn=_noop_wait_for_kernel_idle,
        safe_extract_outputs_fn=lambda outputs: outputs,
        kernel_id="borrowed-kernel",
    )

    assert result == ["[TIMEOUT ERROR: IPython execution exceeded 0 seconds and was interrupted]"]
    # The background thread is still asleep; releasing the client now would
    # close the transport out from under it.
    assert kernel.stop_calls == []

    await asyncio.sleep(_ORPHANED_TASK_SLEEP + 0.5)

    assert kernel.stop_calls == [False]
    assert kernel.stopped_while_task_pending is False


@pytest.mark.asyncio
async def test_borrowed_kernel_stopped_immediately_when_execution_already_finished():
    """The ordinary case: once the background execution has actually
    finished, the borrowed kernel is released without waiting."""
    kernel = FakeBorrowedKernel(lambda: {"outputs": ["ok"]})

    result = await BorrowedKernelExecuteCodeTool(kernel)._execute_via_notebook_manager(
        notebook_manager=FakeNotebookManager(),
        code="1 + 1",
        timeout=5,
        ensure_kernel_alive_fn=lambda: None,
        wait_for_kernel_idle_fn=_noop_wait_for_kernel_idle,
        safe_extract_outputs_fn=lambda outputs: outputs,
        kernel_id="borrowed-kernel",
    )

    assert result == ["ok"]
    assert kernel.stop_calls == [False]
    assert kernel.stopped_while_task_pending is False
