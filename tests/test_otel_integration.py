# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Integration test: activate OTel across the real MCP server and parse the span log.

This test sets JUPYTER_MCP_OTEL_FILE so that the MCP server subprocess
registers the OTel hook handler on startup.  It then exercises real MCP
tool calls via the parametrized client and finally parses the JSONL span
file to verify that hooks fired correctly end-to-end.
"""

import json
import logging
import os
import tempfile

import pytest

from .test_common import MCPClient, timeout_wrapper


# ── Fixture: enable OTel in the MCP server subprocess ─────────────────

@pytest.fixture(scope="session", autouse=True)
def otel_spans_file():
    """Point the MCP server subprocess at a temp JSONL file for OTel spans.

    Because conftest starts the server with subprocess.Popen (which inherits
    the parent environment), setting the env var here is enough.
    """
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="otel_integration_")
    os.close(fd)
    os.environ["JUPYTER_MCP_OTEL_FILE"] = path
    yield path
    os.environ.pop("JUPYTER_MCP_OTEL_FILE", None)
    # Leave the file around for debugging; pytest-tmp will eventually clean up


def _read_spans(path: str) -> list[dict]:
    """Parse all JSONL spans from *path*, tolerating an empty file."""
    try:
        text = open(path).read().strip()  # noqa: SIM115
    except FileNotFoundError:
        return []
    if not text:
        return []
    return [json.loads(line) for line in text.splitlines()]


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@timeout_wrapper(90)
async def test_tool_call_spans_emitted(mcp_client_parametrized: MCPClient, otel_spans_file: str):
    """Run several MCP tool calls and verify that OTel spans appear in the log."""
    async with mcp_client_parametrized:
        # list_kernels is a simple read-only tool — always available
        await mcp_client_parametrized.list_kernels()

        # list_notebooks is another lightweight tool
        await mcp_client_parametrized.list_notebooks()

    # Parse the span log written by the MCP server subprocess
    spans = _read_spans(otel_spans_file)
    span_names = [s["name"] for s in spans]
    logging.info(f"OTel spans collected: {span_names}")

    # We expect at least the two tool call spans
    tool_spans = [s for s in spans if s["name"].startswith("tool_call:")]
    tool_names = {s["attributes"]["tool.name"] for s in tool_spans}
    logging.info(f"Tool span names: {tool_names}")

    assert "list_kernels" in tool_names, f"Expected list_kernels span, got {tool_names}"
    assert "list_notebooks" in tool_names, f"Expected list_notebooks span, got {tool_names}"

    # Every tool span should have start/end times
    for s in tool_spans:
        assert s["start_time"] is not None
        assert s["end_time"] is not None
        assert s["end_time"] >= s["start_time"]


@pytest.mark.asyncio
@timeout_wrapper(90)
async def test_execution_spans_emitted(mcp_client_parametrized: MCPClient, otel_spans_file: str):
    """Code execution must emit BEFORE_EXECUTE/AFTER_EXECUTE spans."""
    async with mcp_client_parametrized:
        result = await mcp_client_parametrized.insert_execute_code_cell(1, "40 + 2")
        assert result is not None
        # Clean up
        await mcp_client_parametrized.delete_cell([1])

    spans = _read_spans(otel_spans_file)
    exec_spans = [s for s in spans if s["name"] == "execute"]
    logging.info(f"Execute spans: {len(exec_spans)}")

    assert len(exec_spans) >= 1, (
        f"Expected at least 1 execute span, got {len(exec_spans)}. "
        "BEFORE_EXECUTE/AFTER_EXECUTE hooks must fire on all execution paths."
    )
    latest = exec_spans[-1]
    assert "kernel.id" in latest["attributes"]
    assert "code.snippet" in latest["attributes"]


@pytest.mark.asyncio
@timeout_wrapper(90)
async def test_lifecycle_spans_emitted(mcp_client_parametrized: MCPClient, otel_spans_file: str):
    """use_notebook triggers a KERNEL_LIFECYCLE span."""
    async with mcp_client_parametrized:
        result = await mcp_client_parametrized.use_notebook("otel_test_nb", "notebook.ipynb")
        logging.info(f"use_notebook result: {result}")

        # Clean up
        await mcp_client_parametrized.unuse_notebook("otel_test_nb")

    spans = _read_spans(otel_spans_file)
    lifecycle_spans = [s for s in spans if s["name"] == "kernel_lifecycle"]
    logging.info(f"Lifecycle spans: {[s['attributes'] for s in lifecycle_spans]}")

    assert len(lifecycle_spans) >= 1, (
        f"Expected at least 1 lifecycle span, got {len(lifecycle_spans)}"
    )
    event_types = {s["attributes"]["event_type"] for s in lifecycle_spans}
    assert "started" in event_types, f"Expected 'started' lifecycle event, got {event_types}"


@pytest.mark.asyncio
@timeout_wrapper(60)
async def test_span_log_summary(otel_spans_file: str):
    """Final summary: print all spans collected during the session."""
    # This test deliberately runs last (alphabetical ordering) to collect
    # the most spans.  It does not call any tools itself — it just reads
    # whatever earlier tests produced.
    spans = _read_spans(otel_spans_file)

    # Group by span name
    by_name: dict[str, int] = {}
    for s in spans:
        by_name[s["name"]] = by_name.get(s["name"], 0) + 1

    logging.info("=== OTel Integration Span Summary ===")
    for name, count in sorted(by_name.items()):
        logging.info(f"  {name}: {count}")
    logging.info(f"  TOTAL: {len(spans)}")

    # At minimum we should have seen *some* spans
    assert len(spans) > 0, "No OTel spans were collected at all"
