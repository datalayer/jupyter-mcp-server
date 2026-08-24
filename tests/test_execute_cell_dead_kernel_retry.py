# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""execute_cell's dead-kernel retry in JUPYTER_SERVER mode.

ExecutionStack reports a kernel it cannot reach as a terminal result rather than
by raising, so the retry that execute_cell wraps around it needs that one failure
to leave execute_via_execution_stack as an exception. These tests drive the real
helper, so nothing on the fault path is stubbed out apart from the ExecutionStack
and the kernel manager the server would provide.
"""

import json
from types import SimpleNamespace

import nbformat
import pytest

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool
from jupyter_mcp_server.utils import MissingKernelError, execute_via_execution_stack

KERNEL_GONE = "HTTP 404: Not Found (Kernel does not exist: kernel-1)"


class DeadKernelExecutionStack:
    """First request reports the kernel gone; a later one runs normally."""

    def __init__(self):
        self.put_kernels: list[str] = []

    def put(self, kernel_id, code, metadata):
        self.put_kernels.append(kernel_id)
        return f"request-{len(self.put_kernels)}"

    def get(self, kernel_id, request_id):
        if request_id == "request-1":
            return {"error": KERNEL_GONE, "pending": False, "request_status": "complete"}
        return {
            "pending": False,
            "request_status": "complete",
            "status": "ok",
            "execution_count": 1,
            "outputs": json.dumps(
                [{"output_type": "stream", "name": "stdout", "text": "ran on the replacement\n"}]
            ),
        }

    def cancel(self, kernel_id):
        pass


class _Extension:
    def __init__(self, execution_stack):
        self._Extension__execution_stack = execution_stack


class _ExtensionManager:
    def __init__(self, extension):
        self.extension_apps = {"jupyter_server_nbmodel": {extension}}


class _FileIdManager:
    def get_id(self, _path):
        return "file-id"

    def index(self, _path):
        return "file-id"


class StaleKernelManager:
    """Still lists the culled kernel, so execute_cell's pre-check passes and the
    request reaches an ExecutionStack that knows the kernel is gone."""

    def __init__(self):
        self.started_paths: list[str] = []

    def list_kernels(self):
        return [{"id": "kernel-1"}]

    async def start_kernel(self, path=None):
        self.started_paths.append(path)
        return "kernel-2"


@pytest.mark.asyncio
async def test_missing_kernel_raises_instead_of_returning_a_formatted_output():
    stack = DeadKernelExecutionStack()
    serverapp = SimpleNamespace(extension_manager=_ExtensionManager(_Extension(stack)))

    with pytest.raises(MissingKernelError) as raised:
        await execute_via_execution_stack(
            serverapp=serverapp, kernel_id="kernel-1", code="print('hi')", poll_interval=0
        )

    assert str(raised.value) == KERNEL_GONE


@pytest.mark.asyncio
async def test_execute_cell_starts_a_replacement_kernel_and_retries_once(monkeypatch):
    stack = DeadKernelExecutionStack()
    serverapp = SimpleNamespace(
        root_dir="/srv/notebooks",
        web_app=SimpleNamespace(settings={"file_id_manager": _FileIdManager()}),
        extension_manager=_ExtensionManager(_Extension(stack)),
    )

    async def no_ydoc(_serverapp, _file_id):
        return None

    async def no_sleep(_seconds):
        return None

    async def no_write(*_args, **_kwargs):
        return None

    async def read_notebook(_path):
        return nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("print('hi')")])

    monkeypatch.setattr(
        "jupyter_mcp_server.jupyter_extension.context.get_server_context",
        lambda: SimpleNamespace(serverapp=serverapp),
    )
    monkeypatch.setattr(
        "jupyter_mcp_server.tools.execute_cell_tool.get_current_notebook_context",
        lambda _manager: ("demo.ipynb", "kernel-1"),
    )
    monkeypatch.setattr("jupyter_mcp_server.tools.execute_cell_tool.get_jupyter_ydoc", no_ydoc)
    monkeypatch.setattr("jupyter_mcp_server.tools.execute_cell_tool.asyncio.sleep", no_sleep)
    monkeypatch.setattr(ExecuteCellTool, "_write_outputs_to_cell", no_write)

    tool = ExecuteCellTool()
    monkeypatch.setattr(tool, "_read_notebook_file_with_retry", read_notebook)
    kernel_manager = StaleKernelManager()

    outputs = await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        kernel_manager=kernel_manager,
        notebook_manager=NotebookManager(),
        cell_index=0,
    )

    assert outputs == ["ran on the replacement\n"]
    assert kernel_manager.started_paths == ["demo.ipynb"]
    assert stack.put_kernels == ["kernel-1", "kernel-2"]
