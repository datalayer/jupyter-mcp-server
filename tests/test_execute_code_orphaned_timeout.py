# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression test for the timeout path in execute_code abandoning its
background execution.

asyncio.Task.cancel() on a task wrapping asyncio.to_thread() cannot stop the
underlying OS thread: kernel.execute(code) keeps running in the background
after a timeout has already been raised back to the caller.
_execute_on_kernel must record that task via track_pending_execution so
is_kernel_busy()/wait_for_kernel_idle() see the still-running execution,
the same way execute_cell_tool.py already does. Without it, a subsequent
execute_code/execute_cell call against the same kernel can start immediately
while the abandoned thread is still talking to the kernel.
"""

import asyncio
import time

import pytest

from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool
from jupyter_mcp_server.utils import is_kernel_busy, wait_for_kernel_idle


class FakeKernel:
    """Minimal stand-in covering the surface _execute_on_kernel uses."""

    def __init__(self, execute_impl):
        self.interrupted = False
        self._execute_impl = execute_impl

    def execute(self, code):
        return self._execute_impl()

    def interrupt(self):
        self.interrupted = True


# The tool's timeout monitoring goes through asyncio.wait_for, which can burn
# real wall clock before control returns to the caller. The background
# execute_impl must still be running by the time we make our first assertion
# (mirrors tests/test_execute_orphaned_timeout.py's _ORPHANED_TASK_SLEEP).
_ORPHANED_TASK_SLEEP = 2.0


async def _noop_wait_for_kernel_idle(kernel, max_wait_seconds=30):
    return None


@pytest.mark.asyncio
async def test_execute_code_timeout_leaves_kernel_marked_busy_until_thread_finishes():
    """Regression for _execute_on_kernel never calling track_pending_execution:
    a timed-out execute_code call must still leave is_kernel_busy() True while
    the orphaned background thread is running."""
    kernel = FakeKernel(lambda: time.sleep(_ORPHANED_TASK_SLEEP))

    result = await ExecuteCodeTool()._execute_on_kernel(
        kernel=kernel,
        kid="kernel-1",
        code="time.sleep(60)",
        timeout=0,
        wait_for_kernel_idle_fn=_noop_wait_for_kernel_idle,
        safe_extract_outputs_fn=lambda outputs: outputs,
    )

    assert result == ["[TIMEOUT ERROR: IPython execution exceeded 0 seconds and was interrupted]"]
    # The tool already returned its [TIMEOUT ...] result, but the fake
    # kernel.execute is still asleep in its background thread.
    assert is_kernel_busy(kernel) is True

    await asyncio.sleep(_ORPHANED_TASK_SLEEP + 0.5)

    assert is_kernel_busy(kernel) is False


@pytest.mark.asyncio
async def test_wait_for_kernel_idle_blocks_until_orphaned_execute_code_finishes():
    """The guard every execute_code/execute_cell call makes before starting a
    new execution must actually wait for a prior timed-out execute_code call
    to finish."""
    kernel = FakeKernel(lambda: time.sleep(_ORPHANED_TASK_SLEEP))

    await ExecuteCodeTool()._execute_on_kernel(
        kernel=kernel,
        kid="kernel-1",
        code="time.sleep(60)",
        timeout=0,
        wait_for_kernel_idle_fn=_noop_wait_for_kernel_idle,
        safe_extract_outputs_fn=lambda outputs: outputs,
    )

    start = time.time()
    await wait_for_kernel_idle(kernel, max_wait_seconds=10)
    elapsed = time.time() - start

    assert elapsed >= 0.5
    assert is_kernel_busy(kernel) is False
