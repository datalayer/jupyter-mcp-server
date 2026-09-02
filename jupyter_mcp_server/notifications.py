# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Telling a subscribed client that a notebook changed.

One worker serves one user, and that user may have several agents. So the
case this exists for is ordinary rather than exotic: agent A edits a cell,
agent B is subscribed to the notebook, and B finds out — through the same
process, with no polling and no second connection.

**The channel is the SDK's, not ours.** At 2026-07-28 a client opens
`subscriptions/listen`, naming the notification types it wants and the
resource URIs it cares about; the SDK acknowledges the subset it will honour
and streams matching events. It even ships the bus. What is missing is
somebody publishing onto it, which is all this module does.

That matters because the obvious reading of "implement subscriptions" is to
write `resources/subscribe`, and on the modern wire the SDK *ignores* that
handler — `get_capabilities` derives the capability from whether
`subscriptions/listen` is served, and the legacy method cannot be dispatched
there at all.

**What is not here**: a change made by somebody *else* — a person typing in
JupyterLab. This server's notebook connections are per call, so between calls
there is no live document to observe. That needs a persistent connection per
subscribed notebook, with its own lifecycle, and it is a different kind of
thing from this.

@module jupyter_mcp_server.notifications
"""

from __future__ import annotations

import logging
import weakref
from typing import Any

logger = logging.getLogger(__name__)

#: The result kinds that mean the document changed.
#:
#: Declared as the set that *mutates* rather than as "not the readers",
#: because a new reading tool added to the negative version would start
#: publishing spurious updates and nothing would say so. A new *writing* tool
#: missing from this one publishes nothing, which is the harmless direction —
#: and the test next door holds this against every kind the server declares,
#: so neither stays wrong for long.
MUTATING_KINDS = frozenset(
    {
        "cell.insert",
        "cell.insert_execute",
        "cell.edit",
        "cell.overwrite",
        "cell.delete",
        "cell.move",
        "cell.execute",
        "cell.clear_output",
    }
)


#: Sessions that asked for a resource through the **legacy** method, and the
#: URIs each asked about.
#:
#: A weak-keyed map, so a session that goes away takes its subscriptions with
#: it. The alternative is an unsubscribe hook that has to fire on every way a
#: connection can end — including the ones that do not run any code — and a
#: subscription nobody can reach is a notification sent for ever to nobody.
_LEGACY: "weakref.WeakKeyDictionary[Any, set[str]]" = weakref.WeakKeyDictionary()


def legacy_subscribe(session: Any, uri: str) -> None:
    """Remember that this session asked about this URI (2025-11-25)."""
    if session is None or not uri:
        return
    _LEGACY.setdefault(session, set()).add(uri)


def legacy_unsubscribe(session: Any, uri: str) -> None:
    """Forget it. Unsubscribing from something never subscribed is not an
    error: the client's intent — *do not tell me about this* — is satisfied
    either way, and refusing it invites a client to retry."""
    if session is None:
        return
    subscribed = _LEGACY.get(session)
    if subscribed is not None:
        subscribed.discard(uri)


def legacy_subscribers(uri: str) -> list[Any]:
    """The sessions to tell about this URI."""
    return [
        session for session, uris in list(_LEGACY.items()) if uri in uris
    ]


def notebook_uri(name: str) -> str:
    """The resource URI of a notebook, as a client subscribed to it."""
    return f"notebook://{name}"


def target_notebook(keywords: dict[str, Any], current: Any) -> str:
    """Which notebook a tool call changed.

    The tool's own `notebook_name` when it named one, and the currently
    activated notebook otherwise — the same resolution the tools use, because
    a subscriber told the wrong notebook changed is worse than one told
    nothing: it refetches the wrong document and believes it is current.
    """
    named = str(keywords.get("notebook_name") or "").strip()
    if named:
        return named
    try:
        return str(current() or "")
    except Exception:  # noqa: BLE001 - no current notebook is not an error
        return ""


def _bus(server: Any) -> Any | None:
    """The SDK's subscription bus, if this server has one.

    Reached through the registered `subscriptions/listen` handler rather than
    constructed: there is exactly one bus and the handler owns it, so making
    a second one here would publish into a channel nobody is listening on.
    """
    try:
        lowlevel = getattr(server, "_lowlevel_server", None)
        entry = lowlevel._request_handlers.get("subscriptions/listen")
        return getattr(entry.handler, "_bus", None) if entry else None
    except Exception:  # noqa: BLE001 - an SDK without the stream is not an error
        return None


async def publish_notebook_updated(server: Any, name: str) -> bool:
    """Say that this notebook changed. Answers whether anything was told.

    Never raises. It runs after a tool has already done its work and
    returned: failing the edit because the *news about* the edit would not go
    out would trade the work for the story about the work, which is the same
    call `tasks.py` makes about its status notifications.
    """
    if not name:
        return False
    bus = _bus(server)
    if bus is None:
        return False
    told = False
    try:
        from mcp.server.subscriptions import ResourceUpdated  # noqa: PLC0415

        await bus.publish(ResourceUpdated(uri=notebook_uri(name)))
        told = True
    except Exception as error:  # noqa: BLE001 - never in the way of the edit
        logger.debug("A notebook update could not be published: %s", error)
    return await _tell_legacy_subscribers(notebook_uri(name)) or told


async def _tell_legacy_subscribers(uri: str) -> bool:
    """The 2025-11-25 half: one notification per subscribed session.

    Both halves run, because both eras can be connected at once — this server
    answers 2026-07-28 and 2025-11-25, and a client on each is two clients.
    Sending only on the wire the *last* subscriber used would leave the other
    silent, which is a bug that only appears when two clients are connected.
    """
    told = False
    for session in legacy_subscribers(uri):
        try:
            await session.send_resource_updated(uri)
            told = True
        except Exception as error:  # noqa: BLE001 - a gone session is not an error
            logger.debug("A subscriber could not be told about %s: %s", uri, error)
            _LEGACY.pop(session, None)
    return told
