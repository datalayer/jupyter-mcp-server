# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for the hook system."""

import pytest
from jupyter_mcp_server.hooks import HookEvent, HookRegistry, with_hooks


class MockHandler:
    """A mock hook handler that records events."""

    def __init__(self, propagate_errors=False):
        self.propagate_errors = propagate_errors
        self.events: list[tuple[HookEvent, dict]] = []

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        self.events.append((event, kwargs))


class FailingHandler:
    """A hook handler that always raises."""

    def __init__(self, propagate_errors=False):
        self.propagate_errors = propagate_errors

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        raise RuntimeError("handler failed")


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton between tests."""
    HookRegistry.reset()
    yield
    HookRegistry.reset()


class TestHookRegistry:
    def test_singleton(self):
        a = HookRegistry.get_instance()
        b = HookRegistry.get_instance()
        assert a is b

    def test_reset(self):
        a = HookRegistry.get_instance()
        HookRegistry.reset()
        b = HookRegistry.get_instance()
        assert a is not b

    @pytest.mark.asyncio
    async def test_fire_delivers_events(self):
        registry = HookRegistry.get_instance()
        handler = MockHandler()
        registry.register(handler)

        await registry.fire(HookEvent.BEFORE_TOOL_CALL, tool_name="test", arguments={})

        assert len(handler.events) == 1
        event, kwargs = handler.events[0]
        assert event == HookEvent.BEFORE_TOOL_CALL
        assert kwargs["tool_name"] == "test"

    @pytest.mark.asyncio
    async def test_fire_returns_context(self):
        registry = HookRegistry.get_instance()
        ctx = await registry.fire(HookEvent.BEFORE_EXECUTE, code="x=1", kernel_id="k1", metadata={})
        assert isinstance(ctx, dict)

    @pytest.mark.asyncio
    async def test_context_passed_through(self):
        """A single handler stashes state in BEFORE and retrieves it in AFTER."""
        registry = HookRegistry.get_instance()

        class MyHandler:
            propagate_errors = False
            final_value = None

            async def on_event(self, event, **kwargs):
                if event == HookEvent.BEFORE_EXECUTE:
                    # Stash the nonce from metadata into context
                    kwargs["context"]["nonce"] = kwargs["metadata"]["nonce"]
                elif event == HookEvent.AFTER_EXECUTE:
                    # Add 2 to the stashed value
                    self.final_value = kwargs["context"]["nonce"] + 2

        handler = MyHandler()
        registry.register(handler)

        ctx = await registry.fire(HookEvent.BEFORE_EXECUTE, code="x", kernel_id="k", metadata={"nonce": 40})
        await registry.fire(HookEvent.AFTER_EXECUTE, code="x", kernel_id="k", metadata={}, outputs=[], context=ctx)

        assert handler.final_value == 42

    @pytest.mark.asyncio
    async def test_handler_ordering(self):
        registry = HookRegistry.get_instance()
        order = []

        class Handler:
            propagate_errors = False

            def __init__(self, name):
                self.name = name

            async def on_event(self, event, **kwargs):
                order.append(self.name)

        registry.register(Handler("first"))
        registry.register(Handler("second"))
        await registry.fire(HookEvent.KERNEL_LIFECYCLE, event_type="started", kernel_id="k", kernel_name="nb")

        assert order == ["first", "second"]

    @pytest.mark.asyncio
    async def test_optional_handler_failure_swallowed(self):
        registry = HookRegistry.get_instance()
        failing = FailingHandler(propagate_errors=False)
        good = MockHandler()
        registry.register(failing)
        registry.register(good)

        await registry.fire(HookEvent.BEFORE_TOOL_CALL, tool_name="t", arguments={})

        # Good handler still received the event
        assert len(good.events) == 1

    @pytest.mark.asyncio
    async def test_critical_handler_failure_propagates(self):
        registry = HookRegistry.get_instance()
        failing = FailingHandler(propagate_errors=True)
        registry.register(failing)

        with pytest.raises(RuntimeError, match="handler failed"):
            await registry.fire(HookEvent.BEFORE_TOOL_CALL, tool_name="t", arguments={})

    @pytest.mark.asyncio
    async def test_unregister(self):
        registry = HookRegistry.get_instance()
        handler = MockHandler()
        registry.register(handler)
        registry.unregister(handler)

        await registry.fire(HookEvent.BEFORE_TOOL_CALL, tool_name="t", arguments={})
        assert len(handler.events) == 0


class TestWithHooksDecorator:
    @pytest.mark.asyncio
    async def test_before_and_after_fired(self):
        registry = HookRegistry.get_instance()
        handler = MockHandler()
        registry.register(handler)

        @with_hooks("my_tool")
        async def my_tool(x=1):
            return "ok"

        result = await my_tool(x=42)
        assert result == "ok"

        assert len(handler.events) == 2
        assert handler.events[0][0] == HookEvent.BEFORE_TOOL_CALL
        assert handler.events[0][1]["tool_name"] == "my_tool"
        assert handler.events[0][1]["arguments"] == {"x": 42}
        assert handler.events[1][0] == HookEvent.AFTER_TOOL_CALL
        assert handler.events[1][1]["result"] == "ok"
        assert handler.events[1][1]["error"] is None

    @pytest.mark.asyncio
    async def test_after_fired_on_error(self):
        registry = HookRegistry.get_instance()
        handler = MockHandler()
        registry.register(handler)

        @with_hooks("failing_tool")
        async def failing_tool():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await failing_tool()

        assert len(handler.events) == 2
        assert handler.events[1][0] == HookEvent.AFTER_TOOL_CALL
        assert handler.events[1][1]["result"] is None
        assert isinstance(handler.events[1][1]["error"], ValueError)

