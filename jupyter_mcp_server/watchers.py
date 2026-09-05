# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Telling a subscribed client that *somebody else* changed a notebook.

`notifications` publishes the changes this server makes: a tool edits a
cell and the subscribers hear of it, through the same process. What it
cannot see is a person typing in JupyterLab, or another server's agent
editing the same document — this server's notebook connections are per
call, and between calls there is no live document to observe.

This is the persistent connection that was missing: one per notebook a
session has bound with `use_notebook`, held for as long as the notebook is
bound, observing the shared document. A change whose transaction origin is
not this client's own is somebody else's, and is published exactly as a
local edit is — through `publish_notebook_updated`, onto the same bus, so a
subscriber cannot tell the two apart, which is the point.

Own edits are not announced twice. The tool that made them publishes on
its way out, and the document's own transaction carries the client's
origin, so the watcher lets those pass. A change that arrives with no
origin at all — an update applied from the wire — is somebody's.

Debounced: a person typing produces a transaction per keystroke, and a
subscriber told once per quarter second learns everything it would have
learned from a hundred notifications. With a ceiling, so that somebody who
never stops typing does not keep the news from going out: a debounce with no
ceiling is starvation waiting for a fast enough typist.

**The changes this server itself makes are folded into the same debounce.**
A tool edits a cell and publishes on its way out; the edit then arrives back
over this connection, and the watcher sees it as somebody's — an update
applied from the wire carries no origin, and the tool's own connection is not
this one. That is two frames for one edit. So a watched notebook's tools hand
their news to `fold` instead of publishing it, and the tool's edit and the
watcher's sight of it collapse into the one notification the subscriber
needed. An unwatched notebook is unaffected: its tools publish as before.

**Which cells moved** is read from the same events. A deep observation of the
cells array names the cell at each changed path, and the inserted cells carry
their own ids; a deletion's id is gone with the cell, and the notebook frame
is what covers that.

@module jupyter_mcp_server.watchers
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: How long the watcher waits after a change before announcing it, so a
#: burst of keystrokes is one notification.
DEBOUNCE_SECONDS = 0.25

#: The longest a change waits, however continuously the document is being
#: edited. Without it the timer is re-armed on every keystroke and a
#: subscriber hears nothing until the typing stops — which for a notebook two
#: agents are working in may be never.
MAX_WAIT_SECONDS = 2.0

#: `JUPYTER_MCP_WATCH_NOTEBOOKS=false` turns the persistent connections off:
#: a deployment that publishes through a configured publisher fed by the
#: document server itself has no use for a second observer.
ENABLED_ENV = "JUPYTER_MCP_WATCH_NOTEBOOKS"


def enabled() -> bool:
    return (os.environ.get(ENABLED_ENV) or "true").strip().lower() not in ("0", "false", "no", "off")


@dataclass
class Watch:
    name: str
    task: asyncio.Task
    pending: asyncio.TimerHandle | None = None
    announced: int = 0
    changes_seen: int = 0
    connection: Any = None
    subscription: Any = field(default=None, repr=False)
    #: The deep observation of the cells array, unobserved with the rest.
    cell_subscription: Any = field(default=None, repr=False)
    #: The loop the watch runs on, so a change folded in from a tool call
    #: arms the same timer the observers do.
    loop: Any = field(default=None, repr=False)
    #: The cells known to have moved since the last announcement.
    cells: set[str] = field(default_factory=set)
    #: When the current burst must be announced by, however it continues.
    deadline: float | None = None
    #: How many times the timer has been armed. A firing carries the number
    #: it was armed with, which is how it knows whether it is still the
    #: announcement anybody is waiting for.
    armed: int = 0
    #: The live cells array, for reading an id back off a changed index.
    ycells: Any = field(default=None, repr=False)


def _hash_of(origin: Any) -> Any:
    try:
        return hash(origin)
    except TypeError:
        return None


def _origin_of(event: Any) -> Any:
    """The transaction's origin, whatever pycrdt's way of saying it is."""
    transaction = getattr(event, "transaction", None)
    origin = getattr(transaction, "origin", None)
    try:
        return origin() if callable(origin) else origin
    except Exception:  # noqa: BLE001 - an origin that cannot be read is nobody's
        return None


def _id_at(ycells: Any, index: Any) -> str:
    """The id of the cell now at this index, or empty."""
    if ycells is None or not isinstance(index, int):
        return ""
    try:
        return str(ycells[index]["id"] or "")
    except Exception:  # noqa: BLE001 - a cell without an id is not an error
        return ""


def _ids_of(event: Any, ycells: Any) -> set[str]:
    """Which cells one deep event names.

    Three shapes, because a notebook is an array of maps of arrays:

    * a change *inside* a cell — its source, its outputs, its metadata —
      arrives with the cell's index at the head of the path, and the id is
      read back off the cell now there;
    * a change to the array itself has an empty path, and the cells it
      inserted are in its delta, carrying their own ids. This is how a
      *moved* cell is named: a move is a delete and an insert of the same
      cell, and the insert half still knows who it is;
    * a **deleted** cell names nobody. Its id went with it, and there is
      nothing left to read. The notebook frame published alongside is what
      tells a subscriber that something it holds may be gone.

    Reading the document from inside its own observer is safe — pycrdt is
    inside the transaction, not holding it against readers — and it is the
    only moment the index and the document agree.
    """
    found: set[str] = set()
    path = list(getattr(event, "path", None) or [])
    if path:
        # The head of the path is the cell; everything after it is where in
        # the cell. `target` is the *deepest* thing that changed, so it is
        # the cell itself only for a change to the cell's own keys.
        found.add(_id_at(ycells, path[0]))
        return {one for one in found if one}
    for part in getattr(event, "delta", None) or []:
        if not isinstance(part, dict):
            continue
        for item in part.get("insert") or []:
            try:
                found.add(str(item["id"] or ""))
            except Exception:  # noqa: BLE001, S112 - not every insert is a cell with an id
                continue
    return {one for one in found if one}


def _drop(subscription: Any) -> None:
    """Let go of a pycrdt subscription, however this version says it."""
    if subscription is None:
        return
    try:
        subscription.drop()
    except Exception:  # noqa: BLE001, S110 - a subscription already gone is gone
        pass


class NotebookWatchers:
    """The persistent document connections, one per bound notebook."""

    def __init__(self) -> None:
        self._watching: dict[str, Watch] = {}
        self._server: Any = None

    def serve(self, server: Any) -> None:
        """Which MCP server's bus to publish on."""
        self._server = server

    def watching(self) -> list[str]:
        return sorted(self._watching)

    def watch(self, name: str, manager: Any) -> bool:
        """Start observing a notebook, if this process can. Answers whether it did.

        Not for a local notebook — there is no collaboration room to join —
        and not without a running loop: a manager exercised outside a
        request has nothing to hand a task to.
        """
        if not enabled() or name in self._watching:
            return False
        try:
            if manager.is_local_notebook(name):
                return False
        except Exception:  # noqa: BLE001 - not knowing is not local
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        task = loop.create_task(self._run(name, manager), name=f"watch-notebook-{name}")
        self._watching[name] = Watch(name=name, task=task)
        return True

    def unwatch(self, name: str) -> bool:
        watch = self._watching.pop(name, None)
        if watch is None:
            return False
        if watch.pending is not None:
            watch.pending.cancel()
        watch.task.cancel()
        return True

    def stop_all(self) -> None:
        for name in list(self._watching):
            self.unwatch(name)

    async def _run(self, name: str, manager: Any) -> None:
        connection = manager.get_notebook_connection(name)
        try:
            client = await connection.__aenter__()
        except Exception as error:  # noqa: BLE001 - a watcher that cannot connect is not an edit that failed
            logger.info("Notebook [%s] cannot be watched: %s", name, error)
            self._watching.pop(name, None)
            return
        watch = self._watching.get(name)
        if watch is None:
            await self._close(connection)
            return
        watch.connection = connection
        own = getattr(client, "_changes_origin", None)
        ydoc = getattr(getattr(client, "_doc", None), "_ydoc", None)
        if ydoc is None or not hasattr(ydoc, "observe"):
            logger.info("Notebook [%s] cannot be watched: its client exposes no document", name)
            await self._close(connection)
            self._watching.pop(name, None)
            return
        watch.loop = asyncio.get_running_loop()
        watch.ycells = getattr(getattr(client, "_doc", None), "ycells", None)

        try:
            self._observe(watch, ydoc, own)
            logger.info("👀 Watching notebook [%s] for changes made elsewhere", name)
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            with_sub = getattr(ydoc, "unobserve", None)
            if callable(with_sub) and watch.subscription is not None:
                try:
                    with_sub(watch.subscription)
                except Exception:  # noqa: BLE001
                    pass
            _drop(watch.cell_subscription)
            await self._close(connection)

    def _observe(self, watch: Watch, ydoc: Any, own: Any) -> None:
        """Start listening to the document, twice.

        Twice because the two observations see different things. The document
        observer sees every transaction, including a change to the notebook's
        metadata, which nobody would hear about if the cells were the only
        thing watched. The deep observation of the cells array is what can
        say *which* cell moved. Both arm the same timer, so the two sightings
        of one transaction are still one notification.
        """
        # pycrdt hands an observer the origin's *hash*, not the origin: an
        # int origin comes back as itself, anything else as `hash(it)`.
        ours = {own, _hash_of(own)} if own is not None else set()

        def changed(_event: Any) -> None:
            if _origin_of(_event) in ours:
                return
            watch.changes_seen += 1
            self._arm(watch)

        def cells_changed(events: Any) -> None:
            for event in events or ():
                if _origin_of(event) in ours:
                    continue
                watch.cells.update(_ids_of(event, watch.ycells))
            self._arm(watch)

        watch.subscription = ydoc.observe(changed)
        if watch.ycells is None or not hasattr(watch.ycells, "observe_deep"):
            return
        try:
            watch.cell_subscription = watch.ycells.observe_deep(cells_changed)
        except Exception as error:  # noqa: BLE001 - the notebook frame still goes out
            logger.info(
                "Notebook [%s] is watched, but which cell moved cannot be read: %s",
                watch.name,
                error,
            )

    def _arm(self, watch: Watch) -> None:
        """Restart this notebook's debounce, without letting it run forever.

        The first change of a burst fixes the moment the burst must be
        announced by. Every change after it pushes the timer back, but never
        past that moment — so continuous typing costs a subscriber one
        notification every `MAX_WAIT_SECONDS` instead of costing it silence.
        """
        loop = watch.loop
        if loop is None:
            return
        now = loop.time()
        if watch.deadline is None:
            watch.deadline = now + MAX_WAIT_SECONDS
        when = min(now + DEBOUNCE_SECONDS, watch.deadline)
        if watch.pending is not None:
            watch.pending.cancel()
        watch.armed += 1
        name, generation = watch.name, watch.armed
        watch.pending = loop.call_at(
            when, lambda: loop.create_task(self._announce(name, generation))
        )

    @staticmethod
    def _on_this_loop(watch: Watch) -> bool:
        """Whether this watch's loop is the one running now.

        A watcher outlives the loop it was started on: the module keeps one
        `NotebookWatchers` for the process, and the next call may arrive on a
        different loop — routinely in the tests, and in any host that
        restarts its loop under a live process. Arming a timer on a closed
        loop *raises*, and it would raise inside a writing tool's result
        wrapper, which is the news about an edit taking the edit down with
        it. Answering `False` sends the caller back to publishing for itself,
        which is what it would have done had nothing been watching.

        Asking whether the loop is *this* one covers the closed one for free:
        a closed loop is not a running loop, so a separate `is_closed()` is a
        guard no input can reach — and an unreachable guard reads like a
        second condition that matters.
        """
        try:
            return watch.loop is not None and asyncio.get_running_loop() is watch.loop
        except RuntimeError:  # no loop running at all: certainly not this one
            return False

    def fold(self, name: str, cells: Any = ()) -> bool:
        """Take a change *this server* just made into the notebook's debounce.

        Answers whether it was taken. A caller told `False` has to publish the
        news itself, which is what an unwatched notebook's tools do.

        This exists because the alternative is two frames for one edit. The
        tool publishes as it returns; a moment later its edit arrives back
        over the watcher's connection, carrying no origin, and is announced
        again as somebody else's. Folding it in makes the tool's edit and the
        watcher's sight of it the same burst — and picks up any *concurrent*
        edit by a person in the same window for free, which is the case a
        plain "suppress the echo" rule would have dropped on the floor.
        """
        watch = self._watching.get(name)
        if watch is None or not self._on_this_loop(watch):
            return False
        watch.cells.update(str(one) for one in cells if one)
        watch.changes_seen += 1
        self._arm(watch)
        return True

    async def _announce(self, name: str, generation: int) -> None:
        """Say what this burst changed, if this is still the burst.

        A timer fires and hands the announcement to a *task*, which runs on
        the next turn of the loop. A change arriving in between re-arms, and
        without the generation both this task and the new timer announce —
        two frames for the burst the debounce exists to make one. The later
        arming wins, because it is the one that will have seen all of it.

        A **counter** rather than a look at the pending timer's deadline,
        which is what this was and which was wrong on a coarse clock: asyncio
        fires a timer when the loop's time is within one clock resolution of
        its deadline, so on Windows a timer set 20 ms out fires with the
        deadline still ~15 ms in the future. Reading that as "a later timer
        is armed" made the notification never arrive at all.
        """
        watch = self._watching.get(name)
        if watch is None or watch.armed != generation:
            return
        watch.pending = None
        watch.deadline = None
        cells = sorted(watch.cells)
        watch.cells.clear()
        from jupyter_mcp_server import notifications  # noqa: PLC0415

        server = self._server
        if server is None:
            try:
                from jupyter_mcp_server.server import mcp as server  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                server = None
        told = await notifications.publish_notebook_updated(server, name, cells)
        if told:
            watch.announced += 1

    @staticmethod
    async def _close(connection: Any) -> None:
        try:
            await connection.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


#: One per process, like the notebook manager it follows.
watchers = NotebookWatchers()
