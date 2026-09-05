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

**A seam, because the in-process bus is not always the right destination.**
The SDK's bus reaches clients attached to *this* process, which is the whole
story for a server somebody runs on their laptop and not the story at all for
a deployment behind several replicas: a client attached to one replica never
hears an edit made through another. `JUPYTER_MCP_PUBLISHER_CLASS` names a
class that takes the event instead — the same shape as the audit-sink and
token-verifier seams next door. Unset, the default here is used, so the
open source server needs no configuration to work.

@module jupyter_mcp_server.notifications
"""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Sequence
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
#: A **strong** reference, and that is the whole point. This was a
#: `WeakKeyDictionary`, so that a session going away took its subscriptions
#: with it — except that nothing else holds a `ServerSession`, so every
#: subscription was collected between the request that made it and the next
#: call. The server advertised `resources.subscribe: true`, accepted the
#: subscribe, reported that it had published, and told nobody, ever. Measured
#: on a deployment and then reproduced in one process against a raw client:
#: the notification is written to a channel with no reader.
#:
#: What replaces the weak key is removal that is *said out loud*: on
#: unsubscribe, on a send that fails (a gone session fails on the next
#: publish, which is the same moment a weak key would have noticed), and past
#: `MAX_SUBSCRIBED_SESSIONS`, oldest first — so a client that subscribes and
#: vanishes without unsubscribing costs one entry until the next publish
#: rather than a leak without a ceiling.
_LEGACY: dict[Any, set[str]] = {}

#: How many subscribed sessions are remembered before the oldest is dropped.
#: A single-user server has one; a shared one has as many as it has clients,
#: and this is far past either.
MAX_SUBSCRIBED_SESSIONS = 256


def legacy_subscribe(session: Any, uri: str) -> None:
    """Remember that this session asked about this URI (2025-11-25)."""
    if session is None or not uri:
        return
    if session not in _LEGACY:
        while len(_LEGACY) >= MAX_SUBSCRIBED_SESSIONS:
            oldest = next(iter(_LEGACY))
            logger.warning(
                "Forgetting the subscriptions of the oldest session: more than "
                "%d are subscribed at once",
                MAX_SUBSCRIBED_SESSIONS,
            )
            _LEGACY.pop(oldest, None)
    _LEGACY.setdefault(session, set()).add(uri)


def legacy_unsubscribe(session: Any, uri: str) -> None:
    """Forget it. Unsubscribing from something never subscribed is not an
    error: the client's intent — *do not tell me about this* — is satisfied
    either way, and refusing it invites a client to retry.

    A session that has unsubscribed from everything is dropped: the map holds
    sessions now, and one with nothing to hear is one to let go of.
    """
    if session is None:
        return
    subscribed = _LEGACY.get(session)
    if subscribed is None:
        return
    subscribed.discard(uri)
    if not subscribed:
        _LEGACY.pop(session, None)


def legacy_subscribers(uri: str) -> list[Any]:
    """The sessions to tell about this URI."""
    return [
        session for session, uris in list(_LEGACY.items()) if uri in uris
    ]


def notebook_uri(name: str) -> str:
    """The resource URI of a notebook, as a client subscribed to it."""
    return f"notebook://{name}"


def cell_uri(name: str, cell_id: str) -> str:
    """The resource URI of one cell — `resources.CELL_RESOURCE` filled in.

    Built here rather than imported from `resources` because that module
    reaches the notebook, and the publisher runs on the way out of a tool
    call that has already finished with it.
    """
    return f"notebook://{name}/cells/{cell_id}"


def changed_cells(result: Any) -> tuple[str, ...]:
    """Which cells a finished tool call says it acted on.

    Read from the result's `_meta` rather than from the tool's arguments,
    because the arguments may name a cell by *index* and an index is not
    something a subscriber can address. The resolver that turns an index into
    a cell already attaches the id it landed on, for the agent's benefit; this
    is the same fact, read once more on the way past.

    Inserting a cell attaches nothing, and that is right: the id of a cell
    that did not exist when somebody subscribed is not an id anybody is
    subscribed to. The notebook frame carries that news.
    """
    meta = getattr(result, "meta", None)
    if not isinstance(meta, dict):
        return ()
    from jupyter_mcp_server.results import meta_key  # noqa: PLC0415

    found: list[str] = []
    for key in ("cell_id", "cell_ids"):
        value = meta.get(meta_key(key))
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            found.extend(str(one) for one in value if one)
    # Ordered, and each said once: two of the eight writing tools resolve
    # twice (a move has a source and a target) and a subscriber told about
    # the same cell twice refetches it twice.
    return tuple(dict.fromkeys(one for one in found if one))


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


#: Names a class with ``async publish(uri) -> bool``, used instead of the
#: in-process bus. See ``resolve_publisher``.
PUBLISHER_CLASS_ENV = "JUPYTER_MCP_PUBLISHER_CLASS"

_publisher: Any | None = None
_publisher_resolved = False


def resolve_publisher() -> Any | None:
    """Build the configured publisher, or ``None`` for the in-process bus.

    A named class that cannot be imported or built is **fatal**, for the
    reason the audit sink gives: an operator who configured delivery and got
    a server running without it has the worst of both — they believe
    subscribers are being told, and they are not.

    Resolved once. A class named per publish would be an import on the path
    of every cell edit.
    """
    global _publisher, _publisher_resolved
    if _publisher_resolved:
        return _publisher
    _publisher_resolved = True
    path = (os.environ.get(PUBLISHER_CLASS_ENV) or "").strip()
    if not path:
        return None
    module_name, _, attribute = path.rpartition(".")
    if not module_name:
        raise RuntimeError(
            f"{PUBLISHER_CLASS_ENV} is {path!r}, which is not a module.Class path"
        )
    try:
        module = importlib.import_module(module_name)
        publisher_class = getattr(module, attribute)
    except Exception as error:
        raise RuntimeError(
            f"{PUBLISHER_CLASS_ENV} names {path!r}, which could not be imported: {error}"
        ) from error
    try:
        publisher = publisher_class()
    except Exception as error:
        raise RuntimeError(
            f"{PUBLISHER_CLASS_ENV} names {path!r}, which could not be constructed: {error}"
        ) from error
    if not callable(getattr(publisher, "publish", None)):
        raise RuntimeError(
            f"{PUBLISHER_CLASS_ENV} names {path!r}, which has no publish(uri) method"
        )
    _publisher = publisher
    return _publisher


def use_publisher(replacement: Any | None) -> None:
    """Swap the publisher — for the tests, and at startup."""
    global _publisher, _publisher_resolved
    _publisher = replacement
    _publisher_resolved = replacement is not None


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


async def publish_notebook_updated(
    server: Any, name: str, cells: Sequence[str] = ()
) -> bool:
    """Say that this notebook changed. Answers whether anything was told.

    `cells` names the cells that moved, when that is known. Each gets its own
    frame on `notebook://<name>/cells/<id>`, **as well as** the notebook's —
    never instead of it. A client subscribed to the notebook asked to hear
    about the notebook, and quietly narrowing that to the cells this server
    happened to identify would go silent on a deletion, which is the one
    change whose id nobody can read afterwards.

    So the notebook frame is what every subscriber can rely on, and the cell
    frames are what lets an agent watching one cell refetch one cell instead
    of the document.

    Never raises. It runs after a tool has already done its work and
    returned: failing the edit because the *news about* the edit would not go
    out would trade the work for the story about the work, which is the same
    call `tasks.py` makes about its status notifications.
    """
    if not name:
        return False
    uris = [notebook_uri(name)]
    uris.extend(cell_uri(name, one) for one in dict.fromkeys(cells) if one)
    # A configured publisher replaces the in-process bus entirely: a
    # deployment that has one is a deployment where this process is not where
    # the subscribers are, so publishing to both would be publishing half the
    # event twice.
    publisher = resolve_publisher()
    if publisher is not None:
        told = False
        for uri in uris:
            try:
                told = bool(await publisher.publish(uri)) or told
            except Exception as error:  # noqa: BLE001 - never in the way of the edit
                logger.debug("A notebook update could not be published: %s", error)
        return told
    told = False
    bus = _bus(server)
    if bus is not None:
        # Each URI on its own. One that cannot be published must not take the
        # rest of the burst with it, and it must not make a publish that did
        # reach somebody answer that nobody was told — the caller counts that
        # answer, and a `False` here is read as "nothing is listening".
        for uri in uris:
            try:
                from mcp.server.subscriptions import ResourceUpdated  # noqa: PLC0415

                await bus.publish(ResourceUpdated(uri=uri))
                told = True
            except Exception as error:  # noqa: BLE001 - never in the way of the edit
                logger.debug("A notebook update could not be published: %s", error)
    # Both halves, always. The legacy half used to be reached only when a bus
    # existed — the `return False` above it saw to that — so a server on an
    # SDK without `subscriptions/listen` told its 2025-11-25 subscribers
    # nothing, which is every subscriber it had.
    reached = False
    for uri in uris:
        reached = await _tell_legacy_subscribers(uri) or reached
    return reached or told


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
            # Info rather than debug: this is the only moment a subscription
            # is noticed to be dead, and a server that quietly stops telling
            # somebody looks exactly like a notebook that stopped changing.
            logger.info("A subscriber could not be told about %s: %s", uri, error)
            _LEGACY.pop(session, None)
    return told
