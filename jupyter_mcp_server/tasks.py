# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# BSD 3-Clause License

"""Tasks: a call whose answer outlives the request that asked for it.

Running a cell can take ten minutes. A client that has to hold a connection
open for those ten minutes loses the work when the laptop sleeps, and a client
that gives up waiting has no way to find out what happened. Tasks are the
protocol's answer: `tools/call` returns a **task id** immediately, the work
goes on, and the client asks for the result whenever it likes — from another
connection, after a reconnect, tomorrow.

MCP defines this. `mcp.types` carries `Task`, `TaskStatus`, `CreateTaskResult`
and the `tasks/*` request shapes; what the SDK does not yet do is *route* the
methods, so this binds them as an extension. `TASKS_EXTENSION` is one
constant, and the day the SDK routes `tasks/*` itself this file loses its
`methods()` and keeps everything else.

Three rules, and most of the code is one of them.

**A task is created only when the client asks for one.** `tools/call` carries
`task` metadata when the client wants a task. Without it the call is
synchronous, exactly as before. Turning a synchronous call into a task
because the server thought it would be slow would break every client that
does not know what a task id is — they would read `CreateTaskResult` as the
tool's output.

**A failure is a failed task, not an empty one.** A tool that raised must end
`failed` carrying the error. The alternative — `completed` with no output —
is the worst outcome available: the client believes the work succeeded and
produced nothing.

**A task nobody can see is gone, not empty.** An expired task answers "no
such task" rather than a record with no result. A client that reads an empty
result as "it produced nothing" is wrong in a way it cannot detect.

@module jupyter_mcp_server.tasks
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CancelTaskRequestParams,
    CancelTaskResult,
    CreateTaskResult,
    GetTaskPayloadRequestParams,
    GetTaskRequestParams,
    GetTaskResult,
    ListTasksResult,
    PaginatedRequestParams,
    Task,
    TaskStatusNotification,
    TaskStatusNotificationParams,
)

logger = logging.getLogger(__name__)

#: The extension identifier, in one place. Tasks are a protocol feature the
#: SDK does not route yet; when it does, this file drops `methods()` and the
#: identifier stops being advertised — nothing else about a task changes.
TASKS_EXTENSION = "io.datalayer/tasks"

#: How long a finished task is kept when the client asks for no particular
#: retention. Long enough to survive a reconnect and a coffee; short enough
#: that a server that is never restarted does not accumulate every result it
#: ever produced.
DEFAULT_TTL_MS = 15 * 60 * 1000

#: The ceiling on what a client may ask to retain. A client asking for a year
#: is asking this process to be a database.
MAX_TTL_MS = 24 * 60 * 60 * 1000

#: What a client is told to wait between polls. Advisory, and worth sending:
#: without it a client picks its own interval, and the one it picks is 100ms.
POLL_INTERVAL_MS = 1000

#: The statuses from which nothing more happens.
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})

#: How many tasks one `tasks/list` returns.
LIST_PAGE = 50

#: The notification the server sends when a task changes state.
TASK_STATUS_NOTIFICATION = "notifications/tasks/status"

#: Where a client puts a key that makes a retried `tools/call` one task.
#: `_meta` is an open map, so this rides along without a protocol change.
IDEMPOTENCY_KEY_META = "io.datalayer/idempotency-key"

#: The store implementation, as `module:Class`. A deployment that wants tasks
#: to survive a restart points this at its own; the default keeps them in this
#: process, which is what a single-user server is anyway.
TASK_STORE_CLASS_ENV = "JUPYTER_MCP_TASK_STORE_CLASS"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class TaskRecord:
    """One task, as this server keeps it.

    The protocol's `Task` is the public half. The result, the error and the
    handle to the work in flight stay here: a client asks for the result
    through `tasks/result`, which is where the *whether it may* is decided.
    """

    task_id: str
    status: str = "working"
    status_message: str | None = None
    created_at: str = field(default_factory=_now_iso)
    last_updated_at: str = field(default_factory=_now_iso)
    #: Milliseconds from creation, or `None` for unlimited.
    ttl: int | None = DEFAULT_TTL_MS
    #: What the call produced. `None` until it produced something.
    result: Any = None
    #: Why it failed, for a `failed` task.
    error: str = ""
    #: The tool this task is running, for `tasks/list` and for a log line.
    tool: str = ""
    #: The work in flight, so `tasks/cancel` can actually stop it.
    handle: Any = field(default=None, repr=False)
    #: Monotonic, for expiry. Not `created_at`: a clock that steps backwards
    #: would make a task un-expire, and NTP steps clocks backwards.
    started_monotonic: float = field(default_factory=time.monotonic)
    #: How to stop the work itself, as opposed to stopping the wait for it.
    #: See `register_interrupt`.
    interrupt: Any = field(default=None, repr=False)
    #: What the client called this call, so a retry is one task.
    idempotency_key: str = ""
    #: A digest of the call the key was used for. A key reused for a
    #: *different* call is a mistake, not a replay — see `intercept_tool_call`.
    request_hash: str = ""
    #: What the work has produced *so far*. See `record_output`.
    #:
    #: Separate from `result`, which is what the tool returned. A task that
    #: never returns — cancelled at minute nine of ten — has no result and
    #: may still have printed five hundred lines, and those lines are the
    #: only thing the person who cancelled it wanted.
    partial: list[Any] = field(default_factory=list, repr=False)

    def public(self) -> Task:
        """The protocol's view. Never the result, never the handle."""
        return Task(
            task_id=self.task_id,
            status=self.status,  # type: ignore[arg-type]
            status_message=self.status_message,
            created_at=self.created_at,
            last_updated_at=self.last_updated_at,
            ttl=self.ttl,
            poll_interval=None if self.is_terminal else POLL_INTERVAL_MS,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def expired(self, *, now: float | None = None) -> bool:
        """Whether this task is past its retention.

        A task still running never expires — a retention that killed work in
        flight would be a timeout wearing retention's name, and the two are
        set by different people for different reasons.
        """
        if self.ttl is None or not self.is_terminal:
            return False
        moment = now if now is not None else time.monotonic()
        return (moment - self.started_monotonic) * 1000 >= self.ttl


class TaskStore(Protocol):
    """Where tasks live between the call that made one and the call that reads it."""

    async def create(self, record: TaskRecord) -> TaskRecord: ...

    async def get(self, task_id: str) -> TaskRecord | None: ...

    async def list(self, *, limit: int = LIST_PAGE) -> list[TaskRecord]: ...

    async def update(self, task_id: str, **changes: Any) -> TaskRecord | None: ...

    async def find_by_key(self, idempotency_key: str) -> TaskRecord | None:
        """The task a previous call under this key created, if it is still here."""
        ...


class MemoryTaskStore:
    """Tasks in this process, which is where a single-user server's are.

    Expiry is applied on read rather than on a timer. A sweeper would need a
    loop that runs whether or not anybody is asking, and the only observable
    difference is memory held a little longer by a server nobody is using.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: TaskRecord) -> TaskRecord:
        async with self._lock:
            self._tasks[record.task_id] = record
            return record

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            if record.expired():
                # Gone, not empty. A caller that read an expired record as a
                # result would read "produced nothing" for work that produced
                # something an hour ago.
                del self._tasks[task_id]
                return None
            return record

    async def list(self, *, limit: int = LIST_PAGE) -> list[TaskRecord]:
        async with self._lock:
            # One pass over a snapshot. The previous version walked
            # `self._tasks.values()` while popping from `self._tasks`, which
            # raises `RuntimeError: dictionary changed size during iteration`
            # the moment anything has expired — so `tasks/list` failed
            # outright rather than degrading.
            live: list[TaskRecord] = []
            for task_id, record in list(self._tasks.items()):
                if record.expired():
                    self._tasks.pop(task_id, None)
                else:
                    live.append(record)
        return sorted(live, key=lambda record: record.created_at, reverse=True)[: max(1, limit)]

    async def update(self, task_id: str, **changes: Any) -> TaskRecord | None:
        async with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return None
            for name, value in changes.items():
                setattr(record, name, value)
            record.last_updated_at = _now_iso()
            return record

    async def find_by_key(self, idempotency_key: str) -> TaskRecord | None:
        if not idempotency_key:
            return None
        async with self._lock:
            for record in list(self._tasks.values()):
                if record.idempotency_key != idempotency_key:
                    continue
                if record.expired():
                    # An expired task is gone, and its key is free again. The
                    # alternative — answering a record whose result has been
                    # swept — hands the client a task it can never read.
                    del self._tasks[record.task_id]
                    return None
                return record
        return None


_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    """The store this process uses, built once.

    `JUPYTER_MCP_TASK_STORE_CLASS` names another as `module:Class`. A name
    that cannot be imported is **fatal** rather than a fallback to memory: a
    deployment that asked for durable tasks and silently got in-process ones
    looks healthy right up to the restart that loses them.
    """
    global _store
    if _store is None:
        _store = _build_store(os.environ.get(TASK_STORE_CLASS_ENV, "").strip())
    return _store


def _build_store(spec: str) -> TaskStore:
    if not spec:
        return MemoryTaskStore()
    module_name, _, class_name = spec.partition(":")
    if not module_name or not class_name:
        raise ValueError(
            f"{TASK_STORE_CLASS_ENV} must be 'module:Class'; got {spec!r}"
        )
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


def use_task_store(replacement: TaskStore | None) -> None:
    """Swap the process store — for the tests, and at startup."""
    global _store
    _store = replacement


#: The task the current call is running as, or `""` when it is synchronous.
#: A context variable rather than an argument, because the thing that knows
#: how to interrupt a kernel is several frames below the thing that knows
#: about tasks, and threading a task id through every tool signature would
#: make tasks a concern of every tool.
CURRENT_TASK: contextvars.ContextVar[str] = contextvars.ContextVar(
    "jupyter_mcp_current_task", default=""
)


def current_task() -> str:
    """The task this call is running as, or `""` for a synchronous call."""
    return CURRENT_TASK.get()


async def register_interrupt(stop: Callable[[], Any], *, store: TaskStore | None = None) -> bool:
    """Say how to stop the work this task is doing.

    Cancelling a task cancels the coroutine that is *waiting* for a cell.
    That is not the same as stopping the cell: the kernel keeps running it,
    keeps holding the sandbox, and keeps costing money, while the task says
    `cancelled` and everybody believes it stopped. A tool that can actually
    stop its work registers that here, and `tasks/cancel` calls it first.

    Answers whether it was registered — `False` for a synchronous call, which
    has no task to attach to and needs none, since the client is still on the
    other end of the connection and can drop it.
    """
    task_id = current_task()
    if not task_id:
        return False
    where = store or get_task_store()
    return await where.update(task_id, interrupt=stop) is not None


async def record_output(outputs: Any, *, store: TaskStore | None = None) -> bool:
    """Put what the work has produced so far where a reader can see it.

    A task's `result` arrives whole when the tool returns. That is the right
    shape for a call that finishes, and no shape at all for one that does
    not: cancel a ten-minute cell at minute nine and the task is `cancelled`
    with `result: None`, though the cell printed five hundred lines and those
    lines are exactly what the person who cancelled it wanted to read.

    So a tool that produces output as it goes says so here, and the record
    keeps it. On cancellation the partial output *becomes* the result — the
    task is terminal, so `tasks/result` will serve it — and on a normal
    return the tool's own result wins, because it is the complete one.

    Replaces rather than appends: the caller holds the whole list of outputs
    so far, and appending would have every reader deduplicate what it reads.

    Answers whether it was recorded — `False` for a synchronous call, which
    has no task to attach to and needs none, since the client is still on the
    other end of the connection.
    """
    task_id = current_task()
    if not task_id:
        return False
    where = store or get_task_store()
    return await where.update(task_id, partial=list(outputs)) is not None


def _idempotency_key(params: Any) -> str:
    """What the client called this call, if it named it."""
    meta = getattr(params, "meta", None) or {}
    try:
        return str(meta.get(IDEMPOTENCY_KEY_META) or "")
    except AttributeError:
        return ""


def _request_hash(params: Any) -> str:
    """A digest of the call, so a key reused for another call is caught.

    Canonical JSON of the tool and its arguments: the same call serialised
    with its keys in another order is the same call, and treating it as a
    different one would turn every retry into a conflict.
    """
    import hashlib
    import json

    body = json.dumps(
        {
            "name": getattr(params, "name", "") or "",
            "arguments": getattr(params, "arguments", None) or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


async def _interrupt(record: TaskRecord) -> bool:
    """Run a task's interrupt, if it has one. Never raises.

    A failure here must not stop the cancellation: the client asked for the
    work to stop, and half of that succeeding is better than none of it. The
    failure is logged, because a kernel that could not be interrupted is a
    sandbox somebody has to go and look at.
    """
    stop = getattr(record, "interrupt", None)
    if stop is None:
        return False
    try:
        outcome = stop()
        if hasattr(outcome, "__await__"):
            await outcome
    # Broad on purpose: the cancel proceeds regardless.
    except Exception as error:
        logger.error(
            "Task %s could not be interrupted (%s); the task is cancelled but "
            "the work it started may still be running",
            record.task_id,
            error,
        )
        return False
    return True


def _no_such_task(task_id: str) -> MCPError:
    """The one answer for a task that never existed and one that expired.

    Deliberately the same. Distinguishing them tells a caller that a task id
    they made up happens to have existed, and tells a caller whose task
    expired nothing more useful than "it is not here".
    """
    return MCPError(code=INVALID_PARAMS, message=f"No such task: {task_id}")


def requested_ttl(metadata: Any) -> int | None:
    """What to retain a task for, given what the client asked.

    `None` from the client means "you decide", which is the default rather
    than "forever": a client that omits the field is not asking this process
    to hold its result until the heat death of the server. An explicit
    `null`, which the protocol allows for unlimited, is honoured but capped —
    the cap is what stops one client's forever from being everybody's memory.
    """
    asked = getattr(metadata, "ttl", None)
    if asked is None:
        return DEFAULT_TTL_MS
    try:
        value = int(asked)
    except (TypeError, ValueError):
        return DEFAULT_TTL_MS
    if value <= 0:
        return DEFAULT_TTL_MS
    return min(value, MAX_TTL_MS)


class TasksExtension(Extension):
    """`tasks/*`, and the interception that creates one.

    The methods are bound rather than implemented on the server because the
    SDK does not route `tasks/*` yet — `SPEC_CLIENT_METHODS` does not name
    them, so `MethodBinding` accepts them. When the SDK does route them, this
    binding will raise at construction, loudly, which is the right way to
    find out.
    """

    identifier = TASKS_EXTENSION

    def __init__(self, store: TaskStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> TaskStore:
        return self._store if self._store is not None else get_task_store()

    def settings(self) -> dict[str, Any]:
        return {
            "defaultTtlMs": DEFAULT_TTL_MS,
            "maxTtlMs": MAX_TTL_MS,
            "pollIntervalMs": POLL_INTERVAL_MS,
        }

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding(
                method="tasks/get",
                params_type=GetTaskRequestParams,
                handler=self._handle_get,
            ),
            MethodBinding(
                method="tasks/list",
                # `tasks/list` takes the ordinary pagination params. Named
                # directly rather than dug out of `ListTasksRequest`, whose
                # `params` is `PaginatedRequestParams | None` — a union, which
                # is not a model class and would fail validation setup.
                params_type=PaginatedRequestParams,
                handler=self._handle_list,
            ),
            MethodBinding(
                method="tasks/cancel",
                params_type=CancelTaskRequestParams,
                handler=self._handle_cancel,
            ),
            MethodBinding(
                method="tasks/result",
                params_type=GetTaskPayloadRequestParams,
                handler=self._handle_result,
            ),
        )

    # -- the four methods ---------------------------------------------------

    async def _handle_get(self, params: Any, ctx: Any) -> GetTaskResult:
        record = await self.store.get(params.task_id)
        if record is None:
            raise _no_such_task(params.task_id)
        return GetTaskResult(**record.public().model_dump(by_alias=False))

    async def _handle_list(self, params: Any, ctx: Any) -> ListTasksResult:
        records = await self.store.list()
        return ListTasksResult(tasks=[record.public() for record in records])

    async def _handle_cancel(self, params: Any, ctx: Any) -> CancelTaskResult:
        record = await self.store.get(params.task_id)
        if record is None:
            raise _no_such_task(params.task_id)
        if not record.is_terminal:
            # Stop the work before stopping the wait for it. Cancelling the
            # handle alone leaves a cell running on a kernel that nobody is
            # watching, holding a sandbox and costing money, while the task
            # says `cancelled`.
            await _interrupt(record)
            handle = record.handle
            if handle is not None:
                handle.cancel()
            record = await self.store.update(
                params.task_id, status="cancelled", status_message="cancelled by the client"
            ) or record
            await self._publish(ctx, record)
        # A terminal task is answered as it is rather than refused: cancelling
        # something that already finished is not an error, it is a race the
        # client lost, and telling it so as a failure teaches it to retry.
        return CancelTaskResult(**record.public().model_dump(by_alias=False))

    async def _handle_result(self, params: Any, ctx: Any) -> Any:
        record = await self.store.get(params.task_id)
        if record is None:
            raise _no_such_task(params.task_id)
        if not record.is_terminal:
            # Not an empty result. A client that got `{}` here would show the
            # user "no output" for work that is still running.
            raise MCPError(
                code=INVALID_PARAMS,
                message=(
                    f"Task {params.task_id} is {record.status}; ask again when it "
                    f"is done, or poll tasks/get every {POLL_INTERVAL_MS}ms"
                ),
            )
        if record.status == "failed":
            raise MCPError(
                code=INVALID_PARAMS, message=record.error or "the task failed"
            )
        return record.result

    # -- creating one -------------------------------------------------------

    async def intercept_tool_call(
        self, params: CallToolRequestParams, ctx: Any, call_next: Callable[[Any], Any]
    ) -> Any:
        """Run the call as a task when the client asked for one.

        Asked for: `params.task` is present. Absent, this passes through and
        the call is synchronous exactly as it was — which is the whole reason
        this is an interception rather than a change to the tools.

        A client may name the call with an idempotency key in `_meta`. A
        retry under the same key answers the task the first attempt created
        rather than starting the work a second time — which matters most
        exactly when it is hardest to notice: the connection dropped after
        the request arrived and before the answer got back, so the client
        retries and, without this, gets two ten-minute cells and pays for
        both.

        The same key on a *different* call is a conflict rather than a
        replay. Answering the first task would hand the client the result of
        work it did not ask for, under an id it believes it just created.
        """
        asked = getattr(params, "task", None)
        if asked is None:
            return await call_next(ctx)

        key = _idempotency_key(params)
        digest = _request_hash(params)
        if key:
            existing = await self.store.find_by_key(key)
            if existing is not None:
                if existing.request_hash != digest:
                    raise MCPError(
                        code=INVALID_PARAMS,
                        message=(
                            f"The idempotency key {key!r} was already used for a "
                            f"different call ({existing.tool or 'another tool'}). "
                            f"Use a new key, or repeat the original call exactly."
                        ),
                    )
                logger.info("Task %s answered again for key %s", existing.task_id, key)
                return CreateTaskResult(task=existing.public())

        record = TaskRecord(
            task_id=f"tsk_{uuid.uuid4().hex}",
            ttl=requested_ttl(asked),
            tool=getattr(params, "name", "") or "",
            idempotency_key=key,
            request_hash=digest,
        )
        await self.store.create(record)
        record.handle = asyncio.ensure_future(self._run(record.task_id, ctx, call_next))
        logger.info(
            "Task %s created for %s, retained for %sms",
            record.task_id,
            record.tool or "a tool call",
            record.ttl,
        )
        return CreateTaskResult(task=record.public())

    async def _publish(self, ctx: Any, record: TaskRecord | None) -> None:
        """Tell the client a task changed, if the session can carry it.

        Best effort, and that is a design position rather than a shrug. The
        protocol makes polling the way a client learns a task's state — that
        is what `poll_interval` on every working task is for — and a
        notification is an optimisation on top. So a session that cannot send
        this one costs latency and nothing else, and failing the task because
        the *news about* the task would not go out would be trading the work
        for the story about the work.

        `ServerSession.send_notification` types its argument as the union of
        spec notifications, which does not yet include this one; the SDK is
        mid-adoption, the same reason `methods()` exists at all. The private
        path is a thin wrapper that dumps the model, so it carries this
        correctly today and will be replaced by the public one the moment the
        union grows.
        """
        if record is None:
            return
        session = getattr(ctx, "session", None)
        if session is None:
            return
        notification = TaskStatusNotification(
            method=TASK_STATUS_NOTIFICATION,
            params=TaskStatusNotificationParams(**record.public().model_dump(by_alias=False)),
        )
        try:
            send = getattr(session, "send_notification", None)
            if send is not None:
                await send(notification)
                return
            await session._notify(notification, request_scoped=False)
        # Broad on purpose: the client still polls.
        except Exception as error:
            logger.debug(
                "The status of task %s could not be sent (%s); the client polls "
                "for it instead",
                record.task_id,
                error,
            )

    async def _run(self, task_id: str, ctx: Any, call_next: Callable[[Any], Any]) -> None:
        """The work, and every way it can end recorded.

        Nothing raises out of here. This runs as a detached task, and an
        exception that escapes goes to the event loop's exception handler —
        which is to say to a log line nobody reads, while the task stays
        `working` for its whole retention and the client polls it forever.
        """
        CURRENT_TASK.set(task_id)
        try:
            result = await call_next(ctx)
        except asyncio.CancelledError:
            # Cancelled by `tasks/cancel`, which already wrote the status. Do
            # not overwrite it with `failed`: "you cancelled this" and "this
            # broke" are different things to show a person.
            await self._mark_cancelled(task_id)
            await self._publish(ctx, await self.store.get(task_id))
            raise
        # Broad on purpose: every failure is a failed task.
        except Exception as error:
            logger.exception("Task %s failed", task_id)
            await self._publish(
                ctx,
                await self.store.update(
                    task_id,
                    status="failed",
                    error=f"{type(error).__name__}: {error}",
                    status_message=str(error)[:200],
                    # `tasks/result` raises for a failed task, so this is not
                    # served — it is kept because a cell that printed for
                    # nine minutes and then raised has the output somebody
                    # needs to see *why*, and throwing it away at the moment
                    # of failure is throwing away the diagnosis.
                    **({"result": partial} if (partial := await self._partial(task_id)) else {}),
                ),
            )
            return
        await self._publish(
            ctx, await self.store.update(task_id, status="completed", result=result)
        )

    async def _partial(self, task_id: str) -> Any:
        """What the task produced so far, or `None`."""
        record = await self.store.get(task_id)
        return record.partial if record is not None and record.partial else None

    async def _mark_cancelled(self, task_id: str) -> None:
        """The cancelled task's last word: what it produced before it stopped.

        **This cannot ask whether the task is still working.** By the time it
        runs, `tasks/cancel` has already written `cancelled` — it writes the
        status, interrupts the work and cancels the handle, and only then does
        the coroutine unwind into here. A guard for "not terminal" therefore
        skips the promotion on the path every cancellation actually takes,
        which is how the first version of this shipped a feature that never
        once ran and a test that stayed green: the test called this directly
        on a still-working record, a state the real flow never reaches.

        It runs here rather than in `_handle_cancel` because it runs *later*:
        the work may have produced more between the cancel arriving and the
        coroutine unwinding, and this is the last moment anything can see it.
        """
        record = await self.store.get(task_id)
        if record is None:
            return
        changes: dict[str, Any] = {}
        if not record.is_terminal:
            # Cancelled from somewhere other than `tasks/cancel` — the handle
            # itself was cancelled, so nothing has written the status yet.
            changes["status"] = "cancelled"
        elif record.status != "cancelled":
            # It completed or failed first. That is the race the client lost,
            # and its own answer stands: replacing a finished result with the
            # half that was visible a moment earlier loses the complete one.
            return
        # What it produced before it was stopped, promoted to the result. The
        # task is terminal, so `tasks/result` serves it — a cancelled cell
        # that printed five hundred lines hands them over instead of
        # answering with nothing.
        if record.partial and record.result is None:
            changes["result"] = record.partial
        if changes:
            await self.store.update(task_id, **changes)


def tasks_extension(store: TaskStore | None = None) -> TasksExtension:
    """The extension, for `MCPServer(extensions=[...])`."""
    return TasksExtension(store)
