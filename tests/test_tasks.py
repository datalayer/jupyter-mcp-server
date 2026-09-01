# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# BSD 3-Clause License

"""Tasks: a call whose answer outlives the request that asked for it.

Three failures these tests are about, and all three are quiet ones. A
synchronous call turned into a task behind a client's back, which the client
reads as the tool's output. A tool that raised reported as a task that
completed with nothing, which the client reads as "it produced nothing". And
an expired task answered as an empty result rather than as gone.

Launch the tests:
```
$ pytest tests/test_tasks.py -v
```
"""

from __future__ import annotations

import asyncio

import pytest
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolRequestParams, CreateTaskResult, TaskMetadata

from jupyter_mcp_server.tasks import (
    DEFAULT_TTL_MS,
    current_task,
    register_interrupt,
    CURRENT_TASK,
    record_output,
    IDEMPOTENCY_KEY_META,
    TASK_STATUS_NOTIFICATION,
    MAX_TTL_MS,
    POLL_INTERVAL_MS,
    TASK_STORE_CLASS_ENV,
    TASKS_EXTENSION,
    MemoryTaskStore,
    TaskRecord,
    TasksExtension,
    _build_store,
    get_task_store,
    requested_ttl,
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


def call(name: str = "execute_cell", *, task: TaskMetadata | None = None) -> CallToolRequestParams:
    return CallToolRequestParams(name=name, arguments={}, task=task)


async def settle() -> None:
    """Let the detached task run to its end."""
    for _ in range(200):
        await asyncio.sleep(0)


class _Params:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


# ---------------------------------------------------------------------------
# A task is created only when the client asks for one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_call_without_task_metadata_stays_synchronous(extension, store):
    """The property everything else rests on.

    A client that does not know what a task id is would read
    `CreateTaskResult` as the tool's output.
    """
    ran = []

    async def call_next(ctx):
        ran.append(1)
        return {"content": "done"}

    answer = await extension.intercept_tool_call(call(), object(), call_next)
    assert answer == {"content": "done"}
    assert ran == [1]
    assert await store.list() == []


@pytest.mark.asyncio
async def test_a_call_that_asks_for_a_task_gets_a_task_id_at_once(extension, store):
    started = asyncio.Event()
    release = asyncio.Event()

    async def call_next(ctx):
        started.set()
        await release.wait()
        return {"content": "done"}

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    assert isinstance(answer, CreateTaskResult)
    assert answer.task.status == "working"
    assert answer.task.task_id.startswith("tsk_")
    # The work is under way rather than waited for.
    await settle()
    assert started.is_set()
    release.set()
    await settle()
    assert (await store.get(answer.task.task_id)).status == "completed"


@pytest.mark.asyncio
async def test_a_working_task_suggests_how_often_to_ask(extension):
    async def call_next(ctx):
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    assert answer.task.poll_interval == POLL_INTERVAL_MS
    answer.task.status = "completed"


# ---------------------------------------------------------------------------
# A failure is a failed task, not an empty one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_tool_that_raised_ends_failed_carrying_the_error(extension, store):
    """`completed` with no output is the worst outcome available: the client
    believes the work succeeded and produced nothing."""

    async def call_next(ctx):
        raise ValueError("the kernel is dead")

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    record = await store.get(answer.task.task_id)
    assert record.status == "failed"
    assert "the kernel is dead" in record.error
    assert record.result is None


@pytest.mark.asyncio
async def test_asking_for_the_result_of_a_failed_task_is_an_error_not_a_blank(
    extension, store
):
    async def call_next(ctx):
        raise ValueError("the kernel is dead")

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    with pytest.raises(MCPError) as refused:
        await extension._handle_result(_Params(answer.task.task_id), object())
    assert "the kernel is dead" in str(refused.value)


@pytest.mark.asyncio
async def test_asking_for_the_result_of_a_running_task_is_refused(extension):
    """A client given `{}` here would show a user "no output" for work that is
    still running."""

    async def call_next(ctx):
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    with pytest.raises(MCPError) as refused:
        await extension._handle_result(_Params(answer.task.task_id), object())
    assert "working" in str(refused.value)


@pytest.mark.asyncio
async def test_the_result_of_a_completed_task_is_what_the_tool_returned(extension):
    async def call_next(ctx):
        return {"content": [{"type": "text", "text": "42"}]}

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    assert await extension._handle_result(_Params(answer.task.task_id), object()) == {
        "content": [{"type": "text", "text": "42"}]
    }


# ---------------------------------------------------------------------------
# A task nobody can see is gone, not empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_expired_task_is_gone_rather_than_a_record_with_no_result(store):
    record = TaskRecord(task_id="tsk_1", status="completed", ttl=1, result={"x": 1})
    record.started_monotonic -= 10  # ten seconds ago, ttl of one millisecond
    await store.create(record)
    assert await store.get("tsk_1") is None
    assert await store.list() == []


@pytest.mark.asyncio
async def test_listing_sweeps_expired_tasks_without_being_asked_for_one_first(store):
    """`list` has to do its own sweeping, and the test above never made it.

    That test calls `get` first, which deletes the expired record itself — so
    by the time `list` ran there was nothing left to sweep and the sweep was
    never executed. It walked the dictionary while popping from it, which
    raises `RuntimeError: dictionary changed size during iteration` on the
    first expired task, and `tasks/list` failed outright rather than
    degrading. Found in review, not here.
    """
    for index in range(3):
        record = TaskRecord(task_id=f"tsk_old_{index}", status="completed", ttl=1)
        record.started_monotonic -= 10
        await store.create(record)
    await store.create(TaskRecord(task_id="tsk_live", status="working"))

    listed = await store.list()

    assert [item.task_id for item in listed] == ["tsk_live"]
    # And they are really gone, not merely left out of the answer.
    assert await store.get("tsk_old_0") is None


@pytest.mark.asyncio
async def test_listing_only_expired_tasks_answers_nothing_rather_than_raising(store):
    """The narrowest case, and the one the old code failed on first: every
    task expired, so the very first iteration pops."""
    record = TaskRecord(task_id="tsk_1", status="completed", ttl=1)
    record.started_monotonic -= 10
    await store.create(record)
    assert await store.list() == []


@pytest.mark.asyncio
async def test_a_task_still_running_does_not_expire(store):
    """Retention that killed work in flight would be a timeout wearing
    retention's name, and the two are set by different people."""
    record = TaskRecord(task_id="tsk_1", status="working", ttl=1)
    record.started_monotonic -= 10
    await store.create(record)
    assert (await store.get("tsk_1")) is not None


@pytest.mark.asyncio
async def test_a_task_that_never_existed_and_one_that_expired_answer_the_same(
    extension, store
):
    """Distinguishing them tells a caller that an id they made up happens to
    have existed."""
    gone = TaskRecord(task_id="tsk_gone", status="completed", ttl=1)
    gone.started_monotonic -= 10
    await store.create(gone)

    messages = []
    for task_id in ("tsk_gone", "tsk_never"):
        with pytest.raises(MCPError) as refused:
            await extension._handle_get(_Params(task_id), object())
        messages.append(str(refused.value).replace(task_id, "<id>"))
    assert messages[0] == messages[1]


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_stops_the_work_and_records_why(extension, store):
    started = asyncio.Event()

    async def call_next(ctx):
        started.set()
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    assert started.is_set()

    cancelled = await extension._handle_cancel(_Params(answer.task.task_id), object())
    assert cancelled.status == "cancelled"
    await settle()
    # The work really stopped rather than the record merely saying so.
    record = await store.get(answer.task.task_id)
    assert record.handle.cancelled() or record.handle.done()


@pytest.mark.asyncio
async def test_cancelling_a_finished_task_answers_it_as_it_is(extension, store):
    """A race the client lost, not an error. Refusing teaches it to retry."""

    async def call_next(ctx):
        return {"content": "done"}

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    cancelled = await extension._handle_cancel(_Params(answer.task.task_id), object())
    assert cancelled.status == "completed"


@pytest.mark.asyncio
async def test_a_cancelled_task_is_not_then_reported_as_failed(extension, store):
    """"You cancelled this" and "this broke" are different things to show."""
    started = asyncio.Event()

    async def call_next(ctx):
        started.set()
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    await extension._handle_cancel(_Params(answer.task.task_id), object())
    await settle()
    assert (await store.get(answer.task.task_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_work_cancelled_from_outside_still_ends_the_task(extension, store):
    """A shutdown cancels every pending task on the loop.

    `tasks/cancel` writes the status before the cancellation lands, so the
    handler in `_run` looks like dead code — until the loop itself does the
    cancelling, and then it is the only thing that stops a task saying
    `working` for its whole retention while nothing is running.
    """
    started = asyncio.Event()

    async def call_next(ctx):
        started.set()
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    record = await store.get(answer.task.task_id)
    record.handle.cancel()  # as a shutdown would, with nobody writing a status
    await settle()
    assert (await store.get(answer.task.task_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_cancelling_a_task_that_does_not_exist_says_so(extension):
    with pytest.raises(MCPError):
        await extension._handle_cancel(_Params("tsk_never"), object())


# ---------------------------------------------------------------------------
# A retry is one task
# ---------------------------------------------------------------------------


def keyed(key: str, name: str = "execute_cell", **arguments) -> CallToolRequestParams:
    return CallToolRequestParams(
        name=name,
        arguments=arguments or {},
        task=TaskMetadata(),
        _meta={IDEMPOTENCY_KEY_META: key},
    )


@pytest.mark.asyncio
async def test_a_retry_under_the_same_key_answers_the_same_task(extension, store):
    """The case this exists for is the one hardest to notice: the connection
    dropped after the request arrived and before the answer got back. Without
    this the client retries and gets two ten-minute cells, and pays for both.
    """
    ran = []

    async def call_next(ctx):
        ran.append(1)
        await asyncio.Event().wait()

    first = await extension.intercept_tool_call(keyed("k1"), object(), call_next)
    await settle()
    again = await extension.intercept_tool_call(keyed("k1"), object(), call_next)

    assert again.task.task_id == first.task.task_id
    assert ran == [1], "the work started a second time"
    assert len(await store.list()) == 1


@pytest.mark.asyncio
async def test_the_same_call_written_differently_is_still_the_same_call(extension):
    """Otherwise every retry that serialised its arguments in another order
    would be refused as a conflict."""

    async def call_next(ctx):
        await asyncio.Event().wait()

    first = await extension.intercept_tool_call(
        keyed("k1", a=1, b=2), object(), call_next
    )
    again = await extension.intercept_tool_call(
        CallToolRequestParams(
            name="execute_cell",
            arguments={"b": 2, "a": 1},
            task=TaskMetadata(),
            _meta={IDEMPOTENCY_KEY_META: "k1"},
        ),
        object(),
        call_next,
    )
    assert again.task.task_id == first.task.task_id


@pytest.mark.asyncio
async def test_the_same_key_on_a_different_call_is_a_conflict(extension):
    """Answering the first task would hand the client the result of work it
    did not ask for, under an id it believes it just created."""

    async def call_next(ctx):
        await asyncio.Event().wait()

    await extension.intercept_tool_call(keyed("k1", cell_index=1), object(), call_next)
    with pytest.raises(MCPError) as refused:
        await extension.intercept_tool_call(keyed("k1", cell_index=2), object(), call_next)
    assert "already used" in str(refused.value)


@pytest.mark.asyncio
async def test_a_different_tool_under_the_same_key_is_a_conflict(extension):
    async def call_next(ctx):
        await asyncio.Event().wait()

    await extension.intercept_tool_call(keyed("k1"), object(), call_next)
    with pytest.raises(MCPError):
        await extension.intercept_tool_call(keyed("k1", name="delete_cell"), object(), call_next)


@pytest.mark.asyncio
async def test_different_keys_are_different_tasks(extension, store):
    ran = []

    async def call_next(ctx):
        ran.append(1)
        await asyncio.Event().wait()

    first = await extension.intercept_tool_call(keyed("k1"), object(), call_next)
    second = await extension.intercept_tool_call(keyed("k2"), object(), call_next)
    await settle()
    assert first.task.task_id != second.task.task_id
    assert len(ran) == 2


@pytest.mark.asyncio
async def test_no_key_means_every_call_is_its_own_task(extension):
    """A client that names nothing gets what it asked for, twice."""
    ran = []

    async def call_next(ctx):
        ran.append(1)
        await asyncio.Event().wait()

    first = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    second = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    assert first.task.task_id != second.task.task_id
    assert len(ran) == 2


@pytest.mark.asyncio
async def test_a_retry_after_the_task_finished_still_answers_it(extension):
    """Within retention, a replay reads the result rather than re-running the
    work — which is the whole value of the key surviving the call."""

    async def call_next(ctx):
        return {"content": "done"}

    first = await extension.intercept_tool_call(keyed("k1"), object(), call_next)
    await settle()
    again = await extension.intercept_tool_call(keyed("k1"), object(), call_next)
    assert again.task.task_id == first.task.task_id
    assert again.task.status == "completed"


@pytest.mark.asyncio
async def test_an_expired_task_frees_its_key(extension, store):
    """The alternative hands the client a task whose result has been swept
    and can never be read."""
    ran = []

    async def call_next(ctx):
        ran.append(1)
        return {"content": "done"}

    first = await extension.intercept_tool_call(keyed("k1"), object(), call_next)
    await settle()
    record = await store.get(first.task.task_id)
    record.ttl = 1
    record.started_monotonic -= 10

    again = await extension.intercept_tool_call(keyed("k1"), object(), call_next)
    await settle()
    assert again.task.task_id != first.task.task_id
    assert len(ran) == 2


@pytest.mark.asyncio
async def test_a_call_without_a_task_is_not_deduplicated(extension, store):
    """The key only names a task. A synchronous call carrying one is still a
    synchronous call, and silently answering an old task's id instead of the
    tool's output would be the worst of both.
    """
    ran = []

    async def call_next(ctx):
        ran.append(1)
        return {"content": "done"}

    params = CallToolRequestParams(
        name="execute_cell", arguments={}, _meta={IDEMPOTENCY_KEY_META: "k1"}
    )
    assert await extension.intercept_tool_call(params, object(), call_next) == {
        "content": "done"
    }
    assert await extension.intercept_tool_call(params, object(), call_next) == {
        "content": "done"
    }
    assert len(ran) == 2 and await store.list() == []


# ---------------------------------------------------------------------------
# Telling the client
# ---------------------------------------------------------------------------


class _Session:
    """A session that records what it was asked to send."""

    def __init__(self, *, explode: bool = False) -> None:
        self.sent: list = []
        self.explode = explode

    async def send_notification(self, notification):
        if self.explode:
            raise RuntimeError("the connection is gone")
        self.sent.append(notification)


class _Ctx:
    def __init__(self, session=None) -> None:
        self.session = session


@pytest.mark.asyncio
async def test_a_finished_task_is_announced(extension):
    session = _Session()

    async def call_next(ctx):
        return {"content": "done"}

    answer = await extension.intercept_tool_call(
        call(task=TaskMetadata()), _Ctx(session), call_next
    )
    await settle()
    assert [n.method for n in session.sent] == [TASK_STATUS_NOTIFICATION]
    assert session.sent[0].params.task_id == answer.task.task_id
    assert session.sent[0].params.status == "completed"


@pytest.mark.asyncio
async def test_a_failed_task_is_announced_as_failed(extension):
    session = _Session()

    async def call_next(ctx):
        raise ValueError("the kernel is dead")

    await extension.intercept_tool_call(call(task=TaskMetadata()), _Ctx(session), call_next)
    await settle()
    assert session.sent[0].params.status == "failed"


@pytest.mark.asyncio
async def test_a_cancelled_task_is_announced(extension, store):
    session = _Session()

    async def call_next(ctx):
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(
        call(task=TaskMetadata()), _Ctx(session), call_next
    )
    await settle()
    await extension._handle_cancel(_Params(answer.task.task_id), _Ctx(session))
    await settle()
    assert any(n.params.status == "cancelled" for n in session.sent)


@pytest.mark.asyncio
async def test_a_notification_that_cannot_be_sent_does_not_fail_the_task(extension, store):
    """The protocol makes polling the way a client learns a task's state —
    that is what `poll_interval` is for. Failing the work because the news
    about the work would not go out would be trading one for the other."""
    session = _Session(explode=True)

    async def call_next(ctx):
        return {"content": "done"}

    answer = await extension.intercept_tool_call(
        call(task=TaskMetadata()), _Ctx(session), call_next
    )
    await settle()
    assert (await store.get(answer.task.task_id)).status == "completed"


@pytest.mark.asyncio
async def test_no_session_is_not_an_error(extension, store):
    async def call_next(ctx):
        return {"content": "done"}

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    assert (await store.get(answer.task.task_id)).status == "completed"


@pytest.mark.asyncio
async def test_the_announcement_carries_no_result(extension):
    """It is a status notification, and a result can be a megabyte of output
    that the client may not even want."""
    session = _Session()

    async def call_next(ctx):
        return {"content": [{"type": "text", "text": "x" * 1000}]}

    await extension.intercept_tool_call(call(task=TaskMetadata()), _Ctx(session), call_next)
    await settle()
    assert "result" not in session.sent[0].params.model_dump()


# ---------------------------------------------------------------------------
# Cancelling stops the work, not just the wait for it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_interrupts_the_work_before_it_stops_waiting(extension, store):
    """The distinction this exists for.

    Cancelling the handle cancels the coroutine *waiting* for a cell. The
    kernel keeps running it, keeps holding the sandbox and keeps costing
    money, while the task says `cancelled` and everybody believes it stopped.
    """
    interrupted = []

    async def call_next(ctx):
        await register_interrupt(lambda: interrupted.append(1))
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    await extension._handle_cancel(_Params(answer.task.task_id), object())
    assert interrupted == [1]


@pytest.mark.asyncio
async def test_an_interrupt_that_fails_does_not_stop_the_cancellation(extension, store):
    """Half of what the client asked for is better than none of it — and the
    log says a kernel is still running so somebody can go and look."""

    async def call_next(ctx):
        await register_interrupt(_explode)
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    cancelled = await extension._handle_cancel(_Params(answer.task.task_id), object())
    assert cancelled.status == "cancelled"


def _explode():
    raise RuntimeError("the kernel is not answering")


@pytest.mark.asyncio
async def test_an_async_interrupt_is_awaited(extension):
    interrupted = []

    async def stop():
        interrupted.append(1)

    async def call_next(ctx):
        await register_interrupt(stop)
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    await extension._handle_cancel(_Params(answer.task.task_id), object())
    assert interrupted == [1]


@pytest.mark.asyncio
async def test_a_task_with_no_interrupt_still_cancels(extension):
    """Most tools cannot stop their work, and that must not make cancel fail."""

    async def call_next(ctx):
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    cancelled = await extension._handle_cancel(_Params(answer.task.task_id), object())
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_a_synchronous_call_has_no_task_to_register_against(extension, store):
    """The client is still on the other end of the connection and can drop
    it, so there is nothing here to interrupt on its behalf."""
    registered = []

    async def call_next(ctx):
        registered.append(await register_interrupt(lambda: None))
        return {"content": "done"}

    await extension.intercept_tool_call(call(), object(), call_next)
    assert registered == [False]


@pytest.mark.asyncio
async def test_a_finished_task_is_not_interrupted(extension, store):
    """Interrupting work that already finished would reach into a kernel
    that has moved on to somebody else's cell."""
    interrupted = []

    async def call_next(ctx):
        await register_interrupt(lambda: interrupted.append(1))
        return {"content": "done"}

    answer = await extension.intercept_tool_call(call(task=TaskMetadata()), object(), call_next)
    await settle()
    await extension._handle_cancel(_Params(answer.task.task_id), object())
    assert interrupted == []


@pytest.mark.asyncio
async def test_the_current_task_is_empty_outside_a_task(extension):
    assert current_task() == ""


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def test_a_client_that_says_nothing_gets_the_default_not_forever():
    assert requested_ttl(TaskMetadata()) == DEFAULT_TTL_MS
    assert requested_ttl(None) == DEFAULT_TTL_MS


def test_a_clients_retention_is_capped():
    """One client's forever must not become everybody's memory."""
    assert requested_ttl(TaskMetadata(ttl=MAX_TTL_MS * 100)) == MAX_TTL_MS


def test_a_nonsense_retention_falls_back_rather_than_crashing():
    assert requested_ttl(TaskMetadata(ttl=0)) == DEFAULT_TTL_MS
    assert requested_ttl(TaskMetadata(ttl=-5)) == DEFAULT_TTL_MS


def test_a_reasonable_retention_is_honoured():
    assert requested_ttl(TaskMetadata(ttl=60_000)) == 60_000


# ---------------------------------------------------------------------------
# The store choice
# ---------------------------------------------------------------------------


def test_no_setting_means_tasks_in_this_process():
    assert isinstance(_build_store(""), MemoryTaskStore)


def test_a_store_that_cannot_be_imported_is_fatal_rather_than_a_fallback():
    """A deployment that asked for durable tasks and silently got in-process
    ones looks healthy right up to the restart that loses them."""
    with pytest.raises(ModuleNotFoundError):
        _build_store("nowhere.at.all:Store")


def test_a_malformed_store_setting_names_the_shape_it_wanted():
    with pytest.raises(ValueError) as refused:
        _build_store("just_a_module")
    assert TASK_STORE_CLASS_ENV in str(refused.value)


def test_the_store_is_built_once(store):
    assert get_task_store() is get_task_store()


# ---------------------------------------------------------------------------
# The extension itself
# ---------------------------------------------------------------------------


def test_the_extension_identifier_is_one_constant():
    """So tasks entering the core protocol is a rename."""
    assert TasksExtension.identifier == TASKS_EXTENSION


def test_the_bound_methods_are_the_four_the_protocol_defines():
    bound = {binding.method for binding in TasksExtension().methods()}
    assert bound == {"tasks/get", "tasks/list", "tasks/cancel", "tasks/result"}


def test_the_settings_tell_a_client_the_retention_and_the_poll_interval():
    settings = TasksExtension().settings()
    assert settings["defaultTtlMs"] == DEFAULT_TTL_MS
    assert settings["maxTtlMs"] == MAX_TTL_MS
    assert settings["pollIntervalMs"] == POLL_INTERVAL_MS


@pytest.mark.asyncio
async def test_a_task_record_never_shows_the_result_or_the_handle(store):
    record = TaskRecord(task_id="tsk_1", status="completed", result={"secret": 1})
    record.handle = object()
    public = record.public().model_dump()
    assert "result" not in public and "handle" not in public
    assert public["task_id"] == "tsk_1"


@pytest.mark.asyncio
async def test_listing_answers_newest_first(store, extension):
    for index in range(3):
        await store.create(
            TaskRecord(task_id=f"tsk_{index}", created_at=f"2026-08-2{index}T00:00:00Z")
        )
    listed = await extension._handle_list(None, object())
    assert [task.task_id for task in listed.tasks] == ["tsk_2", "tsk_1", "tsk_0"]


# ---------------------------------------------------------------------------
# What the work produced before it stopped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_serves_what_the_work_had_already_printed(extension, store):
    """The whole point of recording output, through the path a client takes.

    An earlier version of this test called `_mark_cancelled` directly on a
    still-working record, which is a state the real flow never reaches:
    `tasks/cancel` writes `cancelled` first and *then* the coroutine unwinds.
    So the test passed against code that skipped the promotion on every real
    cancellation — a green test for a feature that never once ran.
    """
    started = asyncio.Event()

    async def call_next(ctx):
        await record_output(["line one", "line two"])
        started.set()
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(
        call(task=TaskMetadata()), object(), call_next
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    await extension._handle_cancel(_Params(answer.task.task_id), object())
    await settle()

    record = await store.get(answer.task.task_id)
    assert record.status == "cancelled"
    assert record.result == ["line one", "line two"]


@pytest.mark.asyncio
async def test_a_cancelled_task_that_printed_nothing_has_no_result(extension, store):
    """Empty is not the same as "we did not look". An empty list here reads
    as a measured zero rather than as nothing to measure, which is the
    distinction `tasks/result`'s two refusals exist for."""

    async def call_next(ctx):
        await asyncio.Event().wait()

    answer = await extension.intercept_tool_call(
        call(task=TaskMetadata()), object(), call_next
    )
    await settle()
    await extension._handle_cancel(_Params(answer.task.task_id), object())
    await settle()
    assert (await store.get(answer.task.task_id)).result is None


@pytest.mark.asyncio
async def test_a_task_that_finished_first_keeps_its_own_result(extension, store):
    """The race the client lost. A call that returned while the cancellation
    was landing has the complete answer, and it must not be replaced by the
    half that was visible a moment earlier."""

    async def call_next(ctx):
        await record_output(["half"])
        return ["whole"]

    answer = await extension.intercept_tool_call(
        call(task=TaskMetadata()), object(), call_next
    )
    await settle()
    await extension._handle_cancel(_Params(answer.task.task_id), object())
    await settle()
    record = await store.get(answer.task.task_id)
    assert record.status == "completed"
    assert record.result == ["whole"]


@pytest.mark.asyncio
async def test_mark_cancelled_leaves_a_finished_task_alone(extension, store):
    """A guard, tested as a guard rather than as a path.

    No current caller can reach it: `_mark_cancelled` runs only from `_run`'s
    `CancelledError` branch, and a call that returned never raises one — so
    mutation shows nothing else catches this. It is here because
    `_mark_cancelled` is a method, the invariant is one line, and the failure
    it prevents is silent: a completed task's own answer replaced by the half
    that was visible a moment earlier.

    Calling it directly is the mistake that shipped the last version of this
    feature. The difference is what is being claimed — that the *guard*
    holds, not that cancellation works.
    """
    await store.create(
        TaskRecord(task_id="tsk_done", status="completed", partial=["half"])
    )
    await extension._mark_cancelled("tsk_done")
    record = await store.get("tsk_done")
    assert record.status == "completed"
    assert record.result is None


@pytest.mark.asyncio
async def test_mark_cancelled_does_not_overwrite_a_result_it_already_has(
    extension, store
):
    await store.create(
        TaskRecord(task_id="tsk_kept", status="cancelled", partial=["half"], result=["whole"])
    )
    await extension._mark_cancelled("tsk_kept")
    assert (await store.get("tsk_kept")).result == ["whole"]


@pytest.mark.asyncio
async def test_a_synchronous_call_records_nothing_and_says_so():
    """It has no task to attach to and needs none: the client is still on the
    other end of the connection."""
    assert await record_output(["out"]) is False


@pytest.mark.asyncio
async def test_the_output_so_far_is_on_the_record(store):
    await store.create(TaskRecord(task_id="tsk_partial"))
    token = CURRENT_TASK.set("tsk_partial")
    try:
        assert await record_output(["one", "two"], store=store) is True
    finally:
        CURRENT_TASK.reset(token)
    assert (await store.get("tsk_partial")).partial == ["one", "two"]


@pytest.mark.asyncio
async def test_recording_replaces_rather_than_appends(store):
    """The caller holds the whole list of outputs so far. Appending would
    make every reader deduplicate what it reads."""
    await store.create(TaskRecord(task_id="tsk_replace"))
    token = CURRENT_TASK.set("tsk_replace")
    try:
        await record_output(["one"], store=store)
        await record_output(["one", "two"], store=store)
    finally:
        CURRENT_TASK.reset(token)
    assert (await store.get("tsk_replace")).partial == ["one", "two"]


@pytest.mark.asyncio
async def test_a_failed_task_keeps_what_it_printed(extension, store):
    """`tasks/result` raises for a failed task, so this is never served — it
    is kept because a cell that printed for nine minutes and then raised has
    the output somebody needs in order to see *why*."""

    async def call_next(ctx):
        await record_output(["progress"])
        raise ValueError("the kernel is dead")

    answer = await extension.intercept_tool_call(
        call(task=TaskMetadata()), object(), call_next
    )
    await settle()
    record = await store.get(answer.task.task_id)
    assert record.status == "failed"
    assert record.result == ["progress"]


# ---------------------------------------------------------------------------
# The execution loop actually calls them
# ---------------------------------------------------------------------------


def _loop_source() -> str:
    import inspect

    from jupyter_mcp_server import utils

    source = inspect.getsource(utils)
    start = source.index("    last_output_count = 0")
    return source[start : source.index("# Get final result", start)]


def test_the_kernel_interrupt_is_registered_by_the_execution_loop():
    """`register_interrupt` was defined, tested, documented and called by no
    tool for as long as it existed — so cancelling said `cancelled` while the
    kernel kept running the cell.

    The *call*, not the name: an earlier version of this asserted
    `"register_interrupt" in body`, which the import line satisfies on its
    own, so deleting the call left the test green.
    """
    assert "await register_interrupt(kernel.interrupt)" in _loop_source()


def test_the_interrupt_is_registered_before_the_wait_begins():
    """Registered inside the loop, a cell cancelled in its first second has
    nothing to interrupt."""
    body = _loop_source()
    assert body.index("register_interrupt") < body.index(
        "while not execution_future.done()"
    )


def test_the_outputs_are_recorded_where_new_ones_are_noticed():
    """Not on the keepalive tick: that fires on a timer whether or not
    anything was produced, so recording there would rewrite the same list
    every few seconds and miss a burst between two ticks."""
    body = _loop_source()
    assert "await record_output(safe_extract_outputs(" in body
    assert body.index("last_output_count = len(current_outputs)") < body.index(
        "await record_output("
    )
    assert body.index("await record_output(") < body.index("emit_execution_progress")


def test_neither_hook_can_fail_the_cell():
    """Both are bookkeeping about the work. Failing a cell because the note
    about the cell would not go out trades the work for the story about it."""
    assert _loop_source().count("except Exception") >= 2
