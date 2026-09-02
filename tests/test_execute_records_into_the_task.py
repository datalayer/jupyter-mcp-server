# Copyright (c) 2023-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Both execution paths put the task's interrupt and its output where they go.

Reported against `b6c494a0`, and reproduced here before it was fixed:

```
non-streaming: interrupt True,  partial 2
streaming:     interrupt False, partial 0
```

`execute_cell(stream=True)` runs its own monitor loop — the documented mode
for long-running cells, and therefore the one most likely to be cancelled —
and it registered no interrupt and recorded no output. Cancelling there left
the kernel running and the task empty, which is the whole failure the two
hooks exist to prevent.

`test_tasks.py` guards this by reading the source of *every* wait loop, found
by shape. This measures it instead: the same fake kernel, the same cell
printing twice, both paths.

Launch the tests:
```
$ pytest tests/test_execute_records_into_the_task.py -v
```
"""

from __future__ import annotations

import contextlib
import time

import pytest

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tasks import (
    CURRENT_TASK,
    MemoryTaskStore,
    TaskRecord,
    use_task_store,
)
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool
from jupyter_mcp_server.utils import execute_cell_with_forced_sync

TWO_OUTPUTS = [
    {"output_type": "stream", "name": "stdout", "text": "one\n"},
    {"output_type": "stream", "name": "stdout", "text": "two\n"},
]


class FakeKernel:
    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


class FakeNotebook:
    """A cell that prints twice, a moment after it starts.

    The delay is what makes the outputs *arrive* rather than be there from
    the beginning: a loop that only ever sees a finished cell would record
    the same thing either way, and prove nothing about streaming.
    """

    def __init__(self, cell):
        self._cell = cell

    def __len__(self):
        return 1

    def __getitem__(self, index):
        return self._cell

    def execute_cell(self, cell_index, kernel):
        time.sleep(1.2)
        self._cell["outputs"] = list(TWO_OUTPUTS)
        time.sleep(1.2)

    @property
    def _doc(self):
        return _Doc(self._cell)


class _Doc:
    def __init__(self, cell):
        self._cell = cell

    @property
    def _ycells(self):
        return [self._cell]


class FakeNotebookManager:
    def __init__(self, notebook, kernel):
        self._notebook = notebook
        self._kernel = kernel

    def get_current_notebook(self):
        return "default"

    def get_code_sandbox_id(self, notebook_name):
        return "kernel-1"

    def get_code_sandbox(self, notebook_name):
        return self._kernel

    @contextlib.asynccontextmanager
    async def _connection(self):
        yield self._notebook

    def get_current_connection(self):
        return self._connection()


@pytest.fixture
def running_task():
    """A task this call is running as, and the store holding it."""
    store = MemoryTaskStore()
    use_task_store(store)
    token = CURRENT_TASK.set("tsk_under_test")
    try:
        yield store
    finally:
        CURRENT_TASK.reset(token)
        use_task_store(None)


async def _seed(store):
    await store.create(TaskRecord(task_id="tsk_under_test"))


@pytest.mark.asyncio
async def test_the_streaming_path_registers_and_records(running_task):
    """The path that was reported broken."""
    await _seed(running_task)
    cell = {"source": "print()", "outputs": []}
    kernel = FakeKernel()

    await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=FakeNotebookManager(FakeNotebook(cell), kernel),
        cell_index=0,
        timeout_seconds=30,
        stream=True,
        progress_interval=1,
        ensure_code_sandbox_alive_fn=lambda: kernel,
    )

    record = await running_task.get("tsk_under_test")
    # Output first: a regression in recording is otherwise masked by the
    # interrupt assertion failing before it, and the two are separate bugs
    # with separate fixes.
    assert len(record.partial) == 2, record.partial
    assert record.interrupt is not None, "no way to stop the cell"


@pytest.mark.asyncio
async def test_the_non_streaming_path_registers_and_records(running_task):
    """The path that already worked, measured the same way so the two are
    held to one standard."""
    await _seed(running_task)
    cell = {"source": "print()", "outputs": []}
    kernel = FakeKernel()

    await execute_cell_with_forced_sync(
        FakeNotebook(cell),
        0,
        kernel,
        timeout_seconds=30,
        progress_interval=1,
    )

    record = await running_task.get("tsk_under_test")
    # Output first: a regression in recording is otherwise masked by the
    # interrupt assertion failing before it, and the two are separate bugs
    # with separate fixes.
    assert len(record.partial) == 2, record.partial
    assert record.interrupt is not None, "no way to stop the cell"


@pytest.mark.asyncio
async def test_the_registered_interrupt_is_the_kernel_s(running_task):
    """Registering something that is not the kernel's interrupt would satisfy
    the check above and stop nothing."""
    await _seed(running_task)
    cell = {"source": "print()", "outputs": []}
    kernel = FakeKernel()

    await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=FakeNotebookManager(FakeNotebook(cell), kernel),
        cell_index=0,
        timeout_seconds=30,
        stream=True,
        progress_interval=1,
        ensure_code_sandbox_alive_fn=lambda: kernel,
    )

    record = await running_task.get("tsk_under_test")
    record.interrupt()
    assert kernel.interrupted is True
