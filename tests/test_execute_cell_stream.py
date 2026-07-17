# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for ExecuteCellTool's streaming (stream=True) branch.

These tests exercise the tool's own control flow with in-memory stand-ins for
the kernel and the notebook connection, so no running Jupyter server or kernel
is required.
"""

import contextlib
import time

import pytest

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool

# 1x1 transparent PNG.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class FakeKernel:
    """Minimal stand-in covering the surface the streaming branch uses."""

    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


class FakeNotebook:
    """Single-cell notebook whose execute_cell runs a caller-supplied callable."""

    def __init__(self, cell, execute_impl):
        self._cell = cell
        self._execute_impl = execute_impl

    def __len__(self):
        return 1

    def __getitem__(self, index):
        return self._cell

    def execute_cell(self, cell_index, kernel):
        return self._execute_impl()


class FakeNotebookManager:
    def __init__(self, notebook):
        self._notebook = notebook

    def get_current_notebook(self):
        return "default"

    def get_kernel_id(self, notebook_name):
        return "kernel-1"

    @contextlib.asynccontextmanager
    async def _connection(self):
        yield self._notebook

    def get_current_connection(self):
        return self._connection()


async def _run_stream(cell, execute_impl, timeout_seconds, kernel):
    manager = FakeNotebookManager(FakeNotebook(cell, execute_impl))
    return await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        server_client=None,
        contents_manager=None,
        kernel_manager=None,
        kernel_spec_manager=None,
        notebook_manager=manager,
        serverapp=None,
        cell_index=0,
        timeout_seconds=timeout_seconds,
        stream=True,
        progress_interval=1,
        ensure_kernel_alive_fn=lambda: kernel,
    )


@pytest.mark.asyncio
async def test_stream_timeout_returns_partial_log():
    """A timeout in streaming mode returns the timeout log it builds, the way the
    non-streaming branch returns its [TIMEOUT ERROR: ...] marker, instead of
    letting CancelledError escape execute()."""
    cell = {"source": "time.sleep(60)", "outputs": []}
    kernel = FakeKernel()

    result = await _run_stream(cell, lambda: time.sleep(5), timeout_seconds=0, kernel=kernel)

    assert isinstance(result, list)
    assert any("[TIMEOUT at" in entry for entry in result if isinstance(entry, str))
    assert kernel.interrupted


@pytest.mark.asyncio
async def test_stream_preserves_image_output_on_terminal_drain():
    """Outputs landing between the final poll and completion are drained after the
    task finishes. extract_output returns ImageContent for image/png, so the drain
    must not assume a str, the way the monitoring loop above it already does not."""
    image_output = {
        "output_type": "display_data",
        "data": {"image/png": PNG_B64},
        "metadata": {},
    }
    cell = {"source": "plt.show()", "outputs": []}

    def execute_impl():
        # The output appears only at completion, after the final poll.
        cell["outputs"] = [image_output]

    result = await _run_stream(cell, execute_impl, timeout_seconds=30, kernel=FakeKernel())

    images = [entry for entry in result if not isinstance(entry, str)]
    assert len(images) == 1
    assert images[0].data == PNG_B64
    assert not any(
        isinstance(entry, str) and entry.startswith("[ERROR:") for entry in result
    )
