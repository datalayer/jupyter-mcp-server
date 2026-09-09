# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# BSD 3-Clause License

"""Cancelling threw away the thing cancelling was supposed to preserve.

`tasks/cancel` interrupted the work and then cancelled the coroutine waiting
for it, in the same breath. Once the interrupt actually worked, that became a
race the output always lost: the interrupt makes the kernel raise, the tool's
own completion path collects what the cell printed and writes it to the
notebook and the result — and `handle.cancel()` arriving first kills the tool
before any of that runs.

Measured on prod1 on 2026-09-07, with a working interrupt and before this
fix: a cell printing every two seconds, cancelled after twenty, answered
`tasks/result` with **no content at all**, and `read_cell` showed the cell
with no outputs and no execution count. The same cell left to finish shows
all eight lines in both places, so the outputs were never the problem — the
moment they were collected was.

So the cancel now gives an interrupted tool a bounded moment to hand back
what it has, and only then cancels it. The status is still `cancelled`: the
client asked for that, and how the work ended does not change what it asked.

Launch the tests:
```
$ pytest tests/test_a_cancelled_cell_hands_back_what_it_printed.py -v
```
"""

from __future__ import annotations

import asyncio
import time

import pytest
from mcp.types import CallToolRequestParams, TaskMetadata

from jupyter_mcp_server.tasks import (
    GRACE_SECONDS,
    MemoryTaskStore,
    TasksExtension,
    register_interrupt,
    use_task_store,
)


@pytest.fixture
def store() -> MemoryTaskStore:
    replacement = MemoryTaskStore()
    use_task_store(replacement)
    yield replacement
    use_task_store(None)


@pytest.fixture
def extension(store: MemoryTaskStore) -> TasksExtension:
    return TasksExtension(store)


def call() -> CallToolRequestParams:
    return CallToolRequestParams(name="execute_cell", arguments={}, task=TaskMetadata())


async def settle() -> None:
    for _ in range(200):
        await asyncio.sleep(0)


class _Params:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


class TestAnInterruptedToolIsHeard:
    @pytest.mark.asyncio
    async def test_it_hands_back_what_it_printed(self, extension, store):
        """The whole point: `cancelled`, and the output is still there."""
        stop = asyncio.Event()

        async def call_next(ctx):
            await register_interrupt(stop.set)
            await stop.wait()
            return {"content": [{"type": "text", "text": "tick 0\ntick 1\n"}]}

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()

        cancelled = await extension._handle_cancel(object(), _Params(answer.task.task_id))
        assert cancelled.status == "cancelled"

        record = await store.get(answer.task.task_id)
        assert record.result == {"content": [{"type": "text", "text": "tick 0\ntick 1\n"}]}, (
            "the cancel threw away what the cell had printed"
        )

    @pytest.mark.asyncio
    async def test_the_client_asked_to_cancel_so_it_says_cancelled(self, extension, store):
        """Even though the tool returned normally during the grace. Reporting
        `completed` would hide that somebody stopped it."""
        stop = asyncio.Event()

        async def call_next(ctx):
            await register_interrupt(stop.set)
            await stop.wait()
            return {"content": "partial"}

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()
        await extension._handle_cancel(object(), _Params(answer.task.task_id))

        assert (await store.get(answer.task.task_id)).status == "cancelled"

    @pytest.mark.asyncio
    async def test_a_tool_that_ignores_the_interrupt_is_still_cancelled(self, extension, store):
        """The grace is bounded. A kernel that will not stop must not hold the
        client on a `tasks/cancel` that cannot succeed."""

        async def call_next(ctx):
            await register_interrupt(lambda: None)
            await asyncio.Event().wait()

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()

        began = time.perf_counter()
        cancelled = await extension._handle_cancel(object(), _Params(answer.task.task_id))
        took = time.perf_counter() - began

        assert cancelled.status == "cancelled"
        assert took < GRACE_SECONDS * 2, f"the cancel waited {took:.1f}s"
        await settle()
        record = await store.get(answer.task.task_id)
        assert record.handle.cancelled() or record.handle.done()


class TestTheGraceIsOnlySpentWhenItCanHelp:
    @pytest.mark.asyncio
    async def test_a_tool_with_no_interrupt_is_cancelled_at_once(self, extension, store):
        """Nothing was delivered, so nothing is going to finish. Waiting only
        makes the client wait to be told the same thing.

        This is the common case — most tools register no interrupt — so a
        grace spent here would slow every cancel in the server.
        """

        async def call_next(ctx):
            await asyncio.Event().wait()

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()

        began = time.perf_counter()
        cancelled = await extension._handle_cancel(object(), _Params(answer.task.task_id))
        took = time.perf_counter() - began

        assert cancelled.status == "cancelled"
        assert took < 0.5, f"it waited {took:.1f}s on a task with nothing to interrupt"

    @pytest.mark.asyncio
    async def test_an_interrupt_that_failed_is_not_waited_on(self, extension, store):
        """`_do_interrupt` answering `False` is a provider saying it cannot
        stop this. Several variants honestly do."""

        def refuses():
            return False

        async def call_next(ctx):
            await register_interrupt(refuses)
            await asyncio.Event().wait()

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()

        began = time.perf_counter()
        await extension._handle_cancel(object(), _Params(answer.task.task_id))
        took = time.perf_counter() - began

        assert took < 0.5, f"it waited {took:.1f}s on an interrupt that was refused"


class TestItStaysOutOfTheWay:
    @pytest.mark.asyncio
    async def test_a_tool_that_raises_during_the_grace_does_not_break_the_cancel(
        self, extension, store
    ):
        """How the work ended is the task's business. The cancel still answers."""
        stop = asyncio.Event()

        async def call_next(ctx):
            await register_interrupt(stop.set)
            await stop.wait()
            raise RuntimeError("the kernel went away")

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()

        cancelled = await extension._handle_cancel(object(), _Params(answer.task.task_id))
        assert cancelled.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancelling_a_finished_task_still_answers_it_as_it_is(self, extension, store):
        """Untouched by the grace: a task that ended before the cancel arrived
        keeps its own last word."""

        async def call_next(ctx):
            return {"content": "done"}

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()
        cancelled = await extension._handle_cancel(object(), _Params(answer.task.task_id))
        assert cancelled.status == "completed"


class TestWhatCountsAsDelivered:
    """`_interrupt` used to answer `True` whenever the call did not raise."""

    @pytest.mark.asyncio
    async def test_an_interrupt_returning_nothing_counts_as_delivered(self, extension, store):
        """Most interrupts return `None` — `JupyterKernelClient.interrupt` and
        `Event.set` among them. Reading that as a refusal would skip the grace
        for every tool that actually can be stopped."""
        stop = asyncio.Event()

        def interrupt_returning_none():
            stop.set()
            return None

        async def call_next(ctx):
            await register_interrupt(interrupt_returning_none)
            await stop.wait()
            return {"content": "kept"}

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()
        await extension._handle_cancel(object(), _Params(answer.task.task_id))

        record = await store.get(answer.task.task_id)
        assert record.result == {"content": "kept"}, "a None-returning interrupt was read as refused"

    @pytest.mark.asyncio
    async def test_an_async_interrupts_answer_is_read_too(self, extension, store):
        """The awaited value is the answer; awaiting and discarding it was the
        bug in the synchronous case."""

        async def refuses():
            return False

        async def call_next(ctx):
            await register_interrupt(refuses)
            await asyncio.Event().wait()

        answer = await extension.intercept_tool_call(call(), object(), call_next)
        await settle()

        began = time.perf_counter()
        await extension._handle_cancel(object(), _Params(answer.task.task_id))
        assert time.perf_counter() - began < 0.5, "an async refusal was waited on"
