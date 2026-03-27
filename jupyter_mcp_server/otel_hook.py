# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""OpenTelemetry hook handler — emits spans for tool calls and kernel executions."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Sequence

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from jupyter_mcp_server.hooks import HookEvent

logger = logging.getLogger(__name__)


class FileSpanExporter(SpanExporter):
    """Exports spans as JSON lines to a file."""

    def __init__(self, file_path: str | Path):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[trace.Span]) -> SpanExportResult:
        try:
            with self._path.open("a") as f:
                for span in spans:
                    readable = span.to_json()
                    # to_json() returns a JSON string; parse and re-dump for single-line JSONL
                    obj = json.loads(readable)
                    f.write(json.dumps(obj) + "\n")
            return SpanExportResult.SUCCESS
        except Exception:
            logger.debug("FileSpanExporter failed", exc_info=True)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass


class OTelHookHandler:
    """Hook handler that creates OpenTelemetry spans for MCP events.

    Paired events (BEFORE/AFTER tool calls and executions) produce a single span
    that starts at BEFORE and ends at AFTER.  One-shot events (KERNEL_LIFECYCLE)
    produce a span that starts and ends immediately.
    """

    propagate_errors = False

    def __init__(self, tracer: trace.Tracer):
        self._tracer = tracer

    async def on_event(self, event: HookEvent, **kwargs) -> None:
        ctx = kwargs.get("context", {})

        if event == HookEvent.BEFORE_TOOL_CALL:
            span = self._tracer.start_span(
                f"tool_call:{kwargs.get('tool_name', 'unknown')}"
            )
            span.set_attribute("tool.name", kwargs.get("tool_name", ""))
            ctx["_otel_span"] = span

        elif event == HookEvent.AFTER_TOOL_CALL:
            span = ctx["_otel_span"]
            error = kwargs.get("error")
            if error is not None:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(error))
            else:
                result = kwargs.get("result")
                span.set_attribute("result.summary", _summarize(result))
            span.end()

        elif event == HookEvent.BEFORE_EXECUTE:
            span = self._tracer.start_span("execute")
            span.set_attribute("kernel.id", kwargs.get("kernel_id", ""))
            code = kwargs.get("code", "")
            span.set_attribute("code.snippet", code[:200])
            ctx["_otel_span"] = span

        elif event == HookEvent.AFTER_EXECUTE:
            span = ctx["_otel_span"]
            error = kwargs.get("error")
            if error is not None:
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(error))
            else:
                outputs = kwargs.get("outputs", [])
                span.set_attribute("output.count", len(outputs))
            span.end()

        elif event == HookEvent.KERNEL_LIFECYCLE:
            span = self._tracer.start_span("kernel_lifecycle")
            span.set_attribute("event_type", kwargs.get("event_type", ""))
            span.set_attribute("kernel.id", kwargs.get("kernel_id", ""))
            span.set_attribute("kernel.name", kwargs.get("kernel_name", ""))
            span.end()

        else:
            raise ValueError(f"Unhandled hook event: {event}")


def _summarize(value: object) -> str:
    """Return a short string summary of a result value."""
    s = str(value)
    return s[:200] if len(s) > 200 else s


def maybe_register_otel() -> None:
    """Register the OTel hook handler if JUPYTER_MCP_OTEL_FILE is set.

    Safe to call from any entry point (CLI, Jupyter extension).
    Does nothing if the env var is unset or OTel deps are missing.
    """
    otel_file = os.environ.get("JUPYTER_MCP_OTEL_FILE")
    if not otel_file:
        return

    from jupyter_mcp_server.hooks import HookRegistry

    handler = create_otel_handler(file_path=otel_file)
    HookRegistry.get_instance().register(handler)
    logger.info(f"OTel hook handler registered, writing spans to {otel_file}")


def create_otel_handler(file_path: str | Path | None = None) -> OTelHookHandler:
    """Create an OTelHookHandler backed by a FileSpanExporter.

    Args:
        file_path: Path for the JSONL span file.  Defaults to
            ``JUPYTER_MCP_OTEL_FILE`` env var or ``./otel_spans.jsonl``.

    Returns:
        A ready-to-register OTelHookHandler instance.
    """
    if file_path is None:
        file_path = os.environ.get("JUPYTER_MCP_OTEL_FILE", "otel_spans.jsonl")

    exporter = FileSpanExporter(file_path)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("jupyter_mcp_server")
    return OTelHookHandler(tracer)
