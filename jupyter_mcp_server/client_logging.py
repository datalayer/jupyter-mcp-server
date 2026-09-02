# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""How much this server tells a client through `notifications/message`.

A client sets a floor with `logging/setLevel` and gets everything at or above
it. Without the method served, a client that sends it is refused `-32601` and
has no way to turn the volume down — which matters because the alternative to
turning it down is turning the connection off.

**A level is per session, not per server.** Two agents of the same user share
a worker; one debugging a notebook and one running a pipeline want different
amounts, and a single global level would have the quiet one shouting or the
loud one silent.

**The default is `info`, and the default is a decision.** `debug` would send
every client a stream it did not ask for and mostly cannot use, and the spec
lets a server pick; `warning` would hide the progress notes a long cell
sends, which are the ones somebody watching a ten-minute execution actually
wants.

@module jupyter_mcp_server.client_logging
"""

from __future__ import annotations

import logging
import weakref
from typing import Any

logger = logging.getLogger(__name__)

#: The spec's levels, least to most severe. Order is the whole point: a floor
#: is only meaningful against a sequence, and this is the sequence RFC 5424
#: gives and the protocol adopts.
LEVELS = (
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
)

#: What a session gets before it asks.
DEFAULT_LEVEL = "info"

#: One floor per session, dropped when the session is.
_LEVELS: "weakref.WeakKeyDictionary[Any, str]" = weakref.WeakKeyDictionary()


def set_level(session: Any, level: str) -> bool:
    """Remember this session's floor. Answers whether it was understood.

    An unknown level is *not* stored and not raised on either: refusing the
    call would be refusing a client for asking about a level a later
    specification added, and storing it would silently mute the session,
    because nothing would ever compare greater than a name with no position.
    """
    if session is None or level not in LEVELS:
        if level not in LEVELS:
            logger.debug("Ignoring an unknown logging level %r", level)
        return False
    _LEVELS[session] = level
    return True


def level_of(session: Any) -> str:
    """This session's floor, or the default."""
    if session is None:
        return DEFAULT_LEVEL
    return _LEVELS.get(session, DEFAULT_LEVEL)


def should_send(session: Any, level: str) -> bool:
    """Whether a message at this level clears the session's floor.

    A message at an unknown level is sent rather than dropped. The failure
    modes are not symmetric: sending something nobody wanted is noise, and
    dropping something somebody needed is an outage they cannot see.
    """
    if level not in LEVELS:
        return True
    return LEVELS.index(level) >= LEVELS.index(level_of(session))


async def log_to_client(session: Any, level: str, data: Any, *, source: str = "") -> bool:
    """Send one message, if the session asked for that much.

    Never raises. This is a note *about* work, sent from paths that are doing
    the work — failing a cell because the note about the cell would not go
    out trades the work for the story about the work.
    """
    if session is None or not should_send(session, level):
        return False
    try:
        await session.send_log_message(level=level, data=data, logger=source or None)
    except Exception as error:  # noqa: BLE001 - never in the way of the work
        logger.debug("A log message could not be sent to the client: %s", error)
        return False
    return True
