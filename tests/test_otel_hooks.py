# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for the OpenTelemetry hook handler."""

import json

import pytest
from jupyter_mcp_server.hooks import HookEvent, HookRegistry, with_hooks
from jupyter_mcp_server.otel_hook import create_otel_handler


@pytest.fixture(autouse=True)
def reset_registry():
    HookRegistry.reset()
    yield
    HookRegistry.reset()


@pytest.fixture()
def otel_spans(tmp_path):
    """Create an OTel handler writing to a temp file; return (handler, spans_path)."""
    spans_file = tmp_path / "spans.jsonl"
    handler = create_otel_handler(file_path=spans_file)
    return handler, spans_file


def _read_spans(path):
    """Parse all JSONL spans from *path*."""
    lines = path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines]


# ── Paired spans: tool calls ──────────────────────────────────────────


class TestToolCallSpans:
    @pytest.mark.asyncio
    async def test_successful_tool_call_emits_span(self, otel_spans):
        handler, spans_file = otel_spans
        registry = HookRegistry.get_instance()
        registry.register(handler)

        @with_hooks("read_cell")
        async def read_cell(cell_index=0):
            return "cell content"

        await read_cell(cell_index=3)

        spans = _read_spans(spans_file)
        assert len(spans) == 1
        span = spans[0]
        assert span["name"] == "tool_call:read_cell"
        assert span["attributes"]["tool.name"] == "read_cell"
        assert "cell content" in span["attributes"]["result.summary"]
        # Span should have start and end times
        assert span["start_time"] is not None
        assert span["end_time"] is not None
        assert span["end_time"] >= span["start_time"]

    @pytest.mark.asyncio
    async def test_failed_tool_call_records_error(self, otel_spans):
        handler, spans_file = otel_spans
        registry = HookRegistry.get_instance()
        registry.register(handler)

        @with_hooks("bad_tool")
        async def bad_tool():
            raise ValueError("something broke")

        with pytest.raises(ValueError, match="something broke"):
            await bad_tool()

        spans = _read_spans(spans_file)
        assert len(spans) == 1
        span = spans[0]
        assert span["name"] == "tool_call:bad_tool"
        assert span["attributes"]["error"] is True
        assert "something broke" in span["attributes"]["error.message"]


# ── Paired spans: code execution ──────────────────────────────────────


class TestExecutionSpans:
    @pytest.mark.asyncio
    async def test_execution_span_records_code_and_outputs(self, otel_spans):
        handler, spans_file = otel_spans
        registry = HookRegistry.get_instance()
        registry.register(handler)

        ctx = await registry.fire(
            HookEvent.BEFORE_EXECUTE, code="print('hello')", kernel_id="k1", metadata={}
        )
        await registry.fire(
            HookEvent.AFTER_EXECUTE,
            code="print('hello')",
            kernel_id="k1",
            metadata={},
            outputs=["hello\n"],
            context=ctx,
        )

        spans = _read_spans(spans_file)
        assert len(spans) == 1
        span = spans[0]
        assert span["name"] == "execute"
        assert span["attributes"]["kernel.id"] == "k1"
        assert span["attributes"]["code.snippet"] == "print('hello')"
        assert span["attributes"]["output.count"] == 1

    @pytest.mark.asyncio
    async def test_execution_error_span(self, otel_spans):
        handler, spans_file = otel_spans
        registry = HookRegistry.get_instance()
        registry.register(handler)

        ctx = await registry.fire(
            HookEvent.BEFORE_EXECUTE, code="1/0", kernel_id="k2", metadata={}
        )
        await registry.fire(
            HookEvent.AFTER_EXECUTE,
            code="1/0",
            kernel_id="k2",
            metadata={},
            outputs=[],
            error=ZeroDivisionError("division by zero"),
            context=ctx,
        )

        spans = _read_spans(spans_file)
        assert len(spans) == 1
        span = spans[0]
        assert span["attributes"]["error"] is True
        assert "division by zero" in span["attributes"]["error.message"]


# ── One-shot spans: kernel lifecycle ──────────────────────────────────


class TestKernelLifecycleSpans:
    @pytest.mark.asyncio
    async def test_lifecycle_event_emits_span(self, otel_spans):
        handler, spans_file = otel_spans
        registry = HookRegistry.get_instance()
        registry.register(handler)

        await registry.fire(
            HookEvent.KERNEL_LIFECYCLE,
            event_type="started",
            kernel_id="k5",
            kernel_name="python3",
        )

        spans = _read_spans(spans_file)
        assert len(spans) == 1
        span = spans[0]
        assert span["name"] == "kernel_lifecycle"
        assert span["attributes"]["event_type"] == "started"
        assert span["attributes"]["kernel.id"] == "k5"
        assert span["attributes"]["kernel.name"] == "python3"


# ── Handler behaviour ─────────────────────────────────────────────────


class TestHandlerBehaviour:
    def test_propagate_errors_is_false(self, otel_spans):
        handler, _ = otel_spans
        assert handler.propagate_errors is False

    @pytest.mark.asyncio
    async def test_unhandled_event_raises(self, otel_spans):
        handler, _ = otel_spans
        with pytest.raises(ValueError, match="Unhandled hook event"):
            await handler.on_event("totally_bogus_event", context={})

    @pytest.mark.asyncio
    async def test_multiple_spans_accumulate(self, otel_spans):
        handler, spans_file = otel_spans
        registry = HookRegistry.get_instance()
        registry.register(handler)

        # Two lifecycle events + one tool call
        await registry.fire(
            HookEvent.KERNEL_LIFECYCLE,
            event_type="started",
            kernel_id="k1",
            kernel_name="python3",
        )
        await registry.fire(
            HookEvent.KERNEL_LIFECYCLE,
            event_type="stopped",
            kernel_id="k1",
            kernel_name="python3",
        )

        @with_hooks("my_tool")
        async def my_tool():
            return 42

        await my_tool()

        spans = _read_spans(spans_file)
        assert len(spans) == 3
        names = [s["name"] for s in spans]
        assert names.count("kernel_lifecycle") == 2
        assert names.count("tool_call:my_tool") == 1
