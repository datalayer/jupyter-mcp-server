# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Pre/post hook system for MCP tool calls and kernel executions."""

import logging
from enum import Enum
from functools import wraps
from typing import Any, ClassVar, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    BEFORE_EXECUTE = "before_execute"
    AFTER_EXECUTE = "after_execute"
    KERNEL_LIFECYCLE = "kernel_lifecycle"


@runtime_checkable
class HookHandler(Protocol):
    propagate_errors: bool

    async def on_event(self, event: HookEvent, **kwargs) -> None: ...


class HookRegistry:
    """Singleton registry for hook handlers.

    Handlers are called in registration order. If a handler has
    propagate_errors=True, its exceptions propagate to the caller.
    Otherwise exceptions are logged and swallowed.
    """

    _instance: ClassVar["HookRegistry | None"] = None

    def __init__(self):
        self._handlers: list[HookHandler] = []

    @classmethod
    def get_instance(cls) -> "HookRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def register(self, handler: HookHandler) -> None:
        self._handlers.append(handler)

    def unregister(self, handler: HookHandler) -> None:
        self._handlers.remove(handler)

    async def fire(self, event: HookEvent, **kwargs) -> dict:
        """Fire an event to all registered handlers.

        Returns a context dict that handlers can write into.
        Pass the returned context to the corresponding AFTER event
        so handlers can correlate before/after pairs.
        """
        ctx = kwargs.pop("context", None) or {}
        for h in self._handlers:
            try:
                await h.on_event(event, context=ctx, **kwargs)
            except Exception:
                if h.propagate_errors:
                    raise
                logger.debug(
                    "Hook handler %s failed on %s", h, event, exc_info=True
                )
        return ctx


def with_hooks(tool_name: str):
    """Decorator that fires BEFORE_TOOL_CALL / AFTER_TOOL_CALL around a tool function."""

    def decorator(fn):
        @wraps(fn)
        async def wrapper(**kwargs):
            hooks = HookRegistry.get_instance()
            ctx = await hooks.fire(
                HookEvent.BEFORE_TOOL_CALL,
                tool_name=tool_name,
                arguments=kwargs,
            )
            try:
                result = await fn(**kwargs)
                await hooks.fire(
                    HookEvent.AFTER_TOOL_CALL,
                    tool_name=tool_name,
                    arguments=kwargs,
                    result=result,
                    error=None,
                    context=ctx,
                )
                return result
            except Exception as e:
                await hooks.fire(
                    HookEvent.AFTER_TOOL_CALL,
                    tool_name=tool_name,
                    arguments=kwargs,
                    result=None,
                    error=e,
                    context=ctx,
                )
                raise

        return wrapper

    return decorator
