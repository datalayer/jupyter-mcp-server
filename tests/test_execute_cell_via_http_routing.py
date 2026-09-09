# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""`execute_cell` routes through the runtime's /execute route when asked.

With `execute_via_http` on and the default jupyter-server variant, the
MCP_SERVER branch hands the cell to `execute_via_execution_stack_http` — with
the document and cell the runtime needs to write outputs server-side — instead
of driving the kernel from this worker. It falls back to the WebSocket path
when the flag is off, when the variant has no such route, or when the document
or cell id cannot be resolved (routing a run whose outputs would land nowhere
is the one thing this must not do).
"""

from __future__ import annotations

import contextlib
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool

LOG = logging.getLogger("test")


class _Notebook:
    """A stand-in for the NbModelClient the connection yields."""

    def __init__(self, cells, ws_url):
        self._cells = cells
        self._ws_url = ws_url

    def __len__(self):
        return len(self._cells)

    def __getitem__(self, index):
        return self._cells[index]


class _Connection:
    def __init__(self, notebook):
        self._notebook = notebook

    async def __aenter__(self):
        return self._notebook

    async def __aexit__(self, *exc):
        return False


class _NotebookManager:
    def __init__(self, notebook, sandbox_id="kid-1"):
        self._notebook = notebook
        self._sandbox_id = sandbox_id

    def get_current_notebook(self):
        return "nb"

    def get_code_sandbox_id(self, name):
        return self._sandbox_id

    def get_current_connection(self):
        return _Connection(self._notebook)


def _config(*, execute_via_http, variant="jupyter-server"):
    return SimpleNamespace(
        execute_via_http=execute_via_http,
        sandbox_variant=variant,
        uses_sandbox_variant=lambda: variant != "jupyter-server",
        code_sandbox_url="https://runtime.example",
        code_sandbox_token="tok",
    )


@contextlib.asynccontextmanager
async def _harness(config):
    """Patch everything the MCP_SERVER branch reaches so execute() runs offline."""

    async def _idle(*a, **k):
        return None

    spy = {}

    async def _fake_http(**kwargs):
        spy.update(kwargs)
        return ["[http output]"]

    with (
        patch("jupyter_mcp_server.config.get_config", return_value=config),
        patch(
            "jupyter_mcp_server.tools.execute_cell_tool.wait_for_code_sandbox_idle",
            _idle,
        ),
        patch(
            "jupyter_mcp_server.tools.execute_cell_tool.execute_via_execution_stack_http",
            _fake_http,
        ),
        patch(
            "jupyter_mcp_server.server_context.ServerContext.get_instance",
            return_value=SimpleNamespace(code_sandbox_auth_headers=None),
        ),
    ):
        yield spy


@pytest.mark.asyncio
async def test_the_http_route_is_taken_with_the_document_and_cell():
    notebook = _Notebook(
        [{"source": "print(1)", "id": "cell-7"}],
        "wss://runtime.example/api/collaboration/room/json:notebook:FILE1?sessionId=s",
    )
    config = _config(execute_via_http=True)
    async with _harness(config) as spy:
        outputs = await ExecuteCellTool().execute(
            mode=ServerMode.MCP_SERVER,
            notebook_manager=_NotebookManager(notebook),
            cell_index=0,
            timeout_seconds=42,
            ensure_code_sandbox_alive_fn=lambda: object(),
        )

    assert outputs == ["[http output]"]
    # It handed the runtime the kernel, the exact document room, and the cell —
    # the three things it needs to run the cell and place the outputs.
    assert spy["kernel_id"] == "kid-1"
    assert spy["document_id"] == "json:notebook:FILE1"
    assert spy["cell_id"] == "cell-7"
    assert spy["code"] == "print(1)"
    assert spy["server_url"] == "https://runtime.example"
    assert spy["timeout"] == 42


@pytest.mark.asyncio
async def test_the_flag_off_keeps_the_websocket_path():
    notebook = _Notebook(
        [{"source": "print(1)", "id": "cell-7"}],
        "wss://runtime.example/api/collaboration/room/json:notebook:FILE1",
    )
    config = _config(execute_via_http=False)
    async with _harness(config) as spy:
        # The WebSocket path needs a kernel client to drive; a bare object has
        # no execute_cell, so the call fails *after* deciding not to route
        # through HTTP. That the HTTP spy stayed empty is the assertion.
        with contextlib.suppress(Exception):
            await ExecuteCellTool().execute(
                mode=ServerMode.MCP_SERVER,
                notebook_manager=_NotebookManager(notebook),
                cell_index=0,
                timeout_seconds=42,
                ensure_code_sandbox_alive_fn=lambda: object(),
            )
    assert spy == {}


@pytest.mark.asyncio
async def test_a_sandbox_variant_keeps_the_websocket_path():
    notebook = _Notebook(
        [{"source": "print(1)", "id": "cell-7"}],
        "wss://runtime.example/api/collaboration/room/json:notebook:FILE1",
    )
    config = _config(execute_via_http=True, variant="modal")
    async with _harness(config) as spy:
        with contextlib.suppress(Exception):
            await ExecuteCellTool().execute(
                mode=ServerMode.MCP_SERVER,
                notebook_manager=_NotebookManager(notebook),
                cell_index=0,
                timeout_seconds=42,
                ensure_code_sandbox_alive_fn=lambda: object(),
            )
    assert spy == {}


@pytest.mark.asyncio
async def test_an_unresolvable_document_falls_back_rather_than_losing_outputs():
    # No room id in the ws_url -> document_id_from_ws_url returns None -> the
    # run must not go through HTTP, where its outputs would land nowhere.
    notebook = _Notebook([{"source": "print(1)", "id": "cell-7"}], "")
    config = _config(execute_via_http=True)
    async with _harness(config) as spy:
        with contextlib.suppress(Exception):
            await ExecuteCellTool().execute(
                mode=ServerMode.MCP_SERVER,
                notebook_manager=_NotebookManager(notebook),
                cell_index=0,
                timeout_seconds=42,
                ensure_code_sandbox_alive_fn=lambda: object(),
            )
    assert spy == {}
