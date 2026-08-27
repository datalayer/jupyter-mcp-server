# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Where a deployment sends its record of who asked for what.

This server has no opinion about auditing. A laptop needs none; a hosted
deployment needs a durable, queryable one with a retention policy; a bank
needs it in a SIEM. Building any one of those in would be wrong for the other
two, and building all three would be three things to maintain for a server
whose job is notebooks.

So there is a seam instead: ``JUPYTER_MCP_AUDIT_SINK_CLASS`` names a class,
this module loads it and registers it, and every tool call reaches it through
the hooks that already exist. Datalayer's hosted gateway keeps its own
append-only ledger this way; somebody else writes JSON lines to a file.

Two rules, and both are about not making auditing worse than none:

- a sink that fails never fails the call it was describing. An audit outage
  that took the server down with it would be an outage caused by the thing
  meant to make outages explicable.
- a sink that fails says so at ``ERROR``, every time. A silently dropped audit
  record is worse than a missing one: it looks like nothing happened.

@module jupyter_mcp_server.audit
"""

from __future__ import annotations

import logging
import os
from importlib import import_module
from typing import Any

from jupyter_mcp_server.hooks import HookEvent, HookRegistry

logger = logging.getLogger(__name__)

#: Names the class that receives this deployment's audit events.
AUDIT_SINK_CLASS_ENV = "JUPYTER_MCP_AUDIT_SINK_CLASS"


class AuditSink:
    """What a sink has to answer. Subclassing is optional; the shape is not.

    A sink is called for every tool call, before and after, with the same
    ``context`` dict both times so it can pair them — that is where a
    duration, or the id assigned to the call, belongs.
    """

    #: Never true for a sink. A sink that propagated its errors would fail
    #: the call it was describing, which is not what auditing is for.
    propagate_errors = False

    async def on_event(self, event: HookEvent, **details: Any) -> None:
        """One thing that happened. `event` says which."""


def load_sink_class(path: str) -> type:
    """Import a sink class named as ``module:Class`` or ``module.Class``.

    The same spelling the token verifier takes, so a deployment configuring
    both does not have to remember two conventions.
    """
    if ":" in path:
        module_name, class_name = path.split(":", 1)
    else:
        module_name, _, class_name = path.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(
            f"Cannot read '{path}' as a class path; use 'package.module:ClassName' "
            "or 'package.module.ClassName'."
        )
    return getattr(import_module(module_name), class_name)


class _Guarded:
    """A sink, wrapped so it cannot take the call down with it.

    Wrapped rather than trusted: a sink is somebody else's code, and the one
    thing it must never do is turn a working tool call into a failed one. The
    failure is logged at ``ERROR`` every time, because a silently dropped
    audit record looks exactly like nothing having happened.
    """

    propagate_errors = False

    def __init__(self, sink: Any, name: str) -> None:
        self._sink = sink
        self._name = name

    async def on_event(self, event: HookEvent, **details: Any) -> None:
        try:
            await self._sink.on_event(event, **details)
        except Exception:  # the whole point of the wrapper
            logger.error(
                "Audit sink %s failed on %s; the call was not recorded",
                self._name,
                getattr(event, "value", event),
                exc_info=True,
            )


def resolve_audit_sink() -> Any | None:
    """Build the configured sink, or ``None`` when none is configured.

    A named class that cannot be imported or built is fatal. An operator who
    configured auditing and got a server running without it has the worst of
    both: they believe calls are being recorded and they are not.
    """
    path = (os.environ.get(AUDIT_SINK_CLASS_ENV) or "").strip()
    if not path:
        return None
    try:
        sink_class = load_sink_class(path)
    except Exception as error:
        raise RuntimeError(
            f"{AUDIT_SINK_CLASS_ENV} names {path!r}, which could not be imported: {error}"
        ) from error
    try:
        sink = sink_class()
    except Exception as error:
        raise RuntimeError(
            f"{AUDIT_SINK_CLASS_ENV} names {path!r}, which could not be constructed: {error}"
        ) from error
    if not callable(getattr(sink, "on_event", None)):
        raise RuntimeError(
            f"{AUDIT_SINK_CLASS_ENV} names {path!r}, which has no on_event(event, **details) "
            "method. See jupyter_mcp_server.audit.AuditSink for the shape."
        )
    return _Guarded(sink, path)


def register_audit_sink() -> Any | None:
    """Put the configured sink on the hook registry. Answers what it registered."""
    sink = resolve_audit_sink()
    if sink is None:
        return None
    HookRegistry.get_instance().register(sink)
    logger.info("Auditing tool calls through %s", sink._name)
    return sink
