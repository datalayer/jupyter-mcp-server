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
