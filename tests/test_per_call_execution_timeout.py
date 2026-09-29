# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The caller's budget must reach the backend, not just the waiting loop."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from jupyter_nbmodel_client import NotebookModel  # type: ignore[import-untyped]

from jupyter_mcp_server import server
from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.sandbox_client import create_jupyter_sandbox_client
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool
from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool
from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool
from jupyter_mcp_server.utils import safe_extract_outputs, wait_for_code_sandbox_idle

from .conftest import JUPYTER_TOKEN
from .test_execute_cell_stream import FakeKernel, FakeNotebookManager


@pytest.fixture(autouse=True)
def execution_config():
    set_config(execution_timeout=2, max_execution_timeout=10, execute_via_http=False)
    yield
    reset_config()


def install_notebook(monkeypatch, notebook, kernel):
    monkeypatch.setattr(server, "notebook_manager", FakeNotebookManager(notebook))
    monkeypatch.setattr(server, "__ensure_code_sandbox_alive", lambda: kernel)
    monkeypatch.setattr(
        server,
        "server_context",
        SimpleNamespace(
            mode=ServerMode.MCP_SERVER,
            sandbox_server_client=None,
            contents_manager=None,
            kernel_manager=None,
        ),
    )
    monkeypatch.setattr(server.cell_ids, "resolve", AsyncMock(return_value=0))


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("tool_name", ["execute_cell", "insert_execute_code_cell"])
async def test_cell_tools_forward_resolved_timeout(monkeypatch, stream, tool_name):
    notebook = NotebookModel()
    notebook.insert_cell(0, "pass", "code")
    execute = Mock(return_value={"status": "ok", "execution_count": 1})
    monkeypatch.setattr(notebook, "execute_cell", execute)
    kernel = FakeKernel()
    install_notebook(monkeypatch, notebook, kernel)
    monkeypatch.setattr(
        InsertCellTool,
        "execute",
        AsyncMock(return_value="Cell inserted successfully at index 0 (code)!"),
    )
    kwargs = {"cell_index": 0, "timeout": 8, "stream": stream}
    if tool_name == "insert_execute_code_cell":
        kwargs["cell_source"] = "pass"
    await getattr(server, tool_name)(**kwargs)
    execute.assert_called_once_with(0, kernel, timeout=13)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "reply", [None, {"status": "ok", "execution_count": None}, {"status": "aborted"}]
)
async def test_cell_without_reply_is_not_completed(monkeypatch, stream, reply):
    notebook = NotebookModel()
    notebook.insert_cell(0, "pass", "code")
    monkeypatch.setattr(notebook, "execute_cell", Mock(return_value=reply))
    call = ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=FakeNotebookManager(notebook),
        cell_index=0,
        timeout_seconds=10,
        stream=stream,
        ensure_code_sandbox_alive_fn=FakeKernel,
    )
    if not stream:
        with pytest.raises(RuntimeError, match="did not complete"):
            await call
        return
    outputs = await call
    assert any("[ERROR:" in output and "did not complete" in output for output in outputs)
    assert not any("[COMPLETED" in output for output in outputs)


@pytest.mark.asyncio
async def test_execute_code_forwards_timeout():
    kernel = SimpleNamespace(execute=Mock(return_value={"outputs": []}))
    await ExecuteCodeTool()._execute_on_kernel(
        code_sandbox_client=kernel,
        kid="k",
        code="pass",
        timeout=10,
        wait_for_code_sandbox_idle_fn=AsyncMock(),
        safe_extract_outputs_fn=safe_extract_outputs,
    )
    kernel.execute.assert_called_once_with("pass", timeout=15)


@pytest.fixture
def short_default_kernel(jupyter_server):
    kernel = create_jupyter_sandbox_client(
        server_url=jupyter_server,
        token=JUPYTER_TOKEN,
        timeout=2,
    )
    try:
        # Startup has its own budget; the regression concerns an already-ready kernel.
        assert kernel.execute("pass", timeout=30)["execution_count"] is not None
        yield kernel
    finally:
        kernel.stop()


@pytest.mark.asyncio
async def test_live_insert_execute_outlasts_client_default(monkeypatch, short_default_kernel):
    notebook = NotebookModel()
    code = "import time; time.sleep(5); print('done')"

    async def insert(self, **kwargs):
        notebook.insert_cell(kwargs["cell_index"], kwargs["cell_source"], kwargs["cell_type"])
        return "Cell inserted successfully at index 0 (code)!"

    monkeypatch.setattr(InsertCellTool, "execute", insert)
    install_notebook(monkeypatch, notebook, short_default_kernel)
    result = await server.insert_execute_code_cell(
        cell_index=0, cell_source=code, timeout=10, stream=True
    )
    assert "done" in " ".join(result.structured_content["outputs"])
    assert notebook[0]["execution_count"] is not None


@pytest.mark.asyncio
async def test_live_code_outlasts_client_default(short_default_kernel):
    outputs = await ExecuteCodeTool()._execute_on_kernel(
        code_sandbox_client=short_default_kernel,
        kid=short_default_kernel.id,
        code="import time; time.sleep(5); print('done')",
        timeout=10,
        wait_for_code_sandbox_idle_fn=wait_for_code_sandbox_idle,
        safe_extract_outputs_fn=safe_extract_outputs,
    )
    assert "done" in " ".join(output for output in outputs if isinstance(output, str))


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_tool_interrupts_before_backend_budget(monkeypatch, stream):
    interrupted = Event()
    kernel = SimpleNamespace(interrupt=Mock(side_effect=interrupted.set))
    notebook = NotebookModel()
    notebook.insert_cell(0, "pass", "code")

    def execute(index, client, *, timeout):
        assert timeout == 6
        assert interrupted.wait(timeout), "the tool must interrupt before the backend expires"
        return {"status": "error", "execution_count": 1}

    monkeypatch.setattr(notebook, "execute_cell", execute)
    outputs = await ExecuteCellTool().execute(
        mode=ServerMode.MCP_SERVER,
        notebook_manager=FakeNotebookManager(notebook),
        cell_index=0,
        timeout_seconds=1,
        stream=stream,
        ensure_code_sandbox_alive_fn=lambda: kernel,
    )
    kernel.interrupt.assert_called_once()
    assert any("TIMEOUT" in output for output in outputs)
    assert not any("COMPLETED" in output for output in outputs)
