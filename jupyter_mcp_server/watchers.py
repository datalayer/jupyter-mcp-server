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
learned from a hundred notifications.

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
        loop = asyncio.get_running_loop()

        # pycrdt hands an observer the origin's *hash*, not the origin: an
        # int origin comes back as itself, anything else as `hash(it)`.
        ours = {own, _hash_of(own)} if own is not None else set()

        def changed(event: Any) -> None:
            if _origin_of(event) in ours:
                return
            watch.changes_seen += 1
            if watch.pending is not None:
                watch.pending.cancel()
            watch.pending = loop.call_later(DEBOUNCE_SECONDS, lambda: loop.create_task(self._announce(name)))

        try:
            watch.subscription = ydoc.observe(changed)
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
            await self._close(connection)

    async def _announce(self, name: str) -> None:
        watch = self._watching.get(name)
        if watch is None:
            return
        watch.pending = None
        from jupyter_mcp_server import notifications  # noqa: PLC0415

        server = self._server
        if server is None:
            try:
                from jupyter_mcp_server.server import mcp as server  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                server = None
        told = await notifications.publish_notebook_updated(server, name)
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
