# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""execute_cell's kernel rebinding in JUPYTER_SERVER mode.

When execute_cell replaces a culled kernel it has to register the replacement
where get_current_notebook_context reads it back from, otherwise every call
starts another kernel. These tests drive the real NotebookManager and the real
context lookup, so the registration round-trip is what is under test.
"""

import json
from types import SimpleNamespace

import nbformat
import pytest

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool
from jupyter_mcp_server.utils import get_current_notebook_context


class WorkingExecutionStack:
    def __init__(self):
        self.put_kernels: list[str] = []

    def put(self, kernel_id, code, metadata):
        self.put_kernels.append(kernel_id)
        return f"request-{len(self.put_kernels)}"

    def get(self, kernel_id, request_id):
        return {
            "pending": False,
            "request_status": "complete",
            "status": "ok",
            "execution_count": 1,
            "outputs": json.dumps([{"output_type": "stream", "name": "stdout", "text": "ran\n"}]),
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


class CulledKernelManager:
    """The kernel the notebook is bound to is gone; replacements stay alive."""

    def __init__(self):
        self.started_paths: list[str] = []
        self.live: set[str] = set()

    def list_kernels(self):
        return [{"id": kernel_id} for kernel_id in sorted(self.live)]

    async def start_kernel(self, path=None):
        self.started_paths.append(path)
        kernel_id = f"kernel-{len(self.started_paths) + 1}"
        self.live.add(kernel_id)
        return kernel_id


@pytest.fixture
def jupyter_server_mode(monkeypatch):
    stack = WorkingExecutionStack()
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
    monkeypatch.setattr("jupyter_mcp_server.tools.execute_cell_tool.get_jupyter_ydoc", no_ydoc)
    monkeypatch.setattr("jupyter_mcp_server.tools.execute_cell_tool.asyncio.sleep", no_sleep)
    monkeypatch.setattr(ExecuteCellTool, "_write_outputs_to_cell", no_write)

    tool = ExecuteCellTool()
    monkeypatch.setattr(tool, "_read_notebook_file_with_retry", read_notebook)
    return tool, stack


def _enrolled_manager() -> NotebookManager:
    """A manager in the shape the extension auto-enroll leaves behind: the
    notebook is keyed by name while its path is a separate field."""
    manager = NotebookManager()
    manager.add_notebook(
        "default",
        {"id": "kernel-1"},
        server_url="local",
        token=None,
        path="notebook.ipynb",
    )
    manager.set_current_notebook("default")
    return manager


@pytest.mark.asyncio
async def test_replacement_kernel_is_reused_by_the_next_execution(jupyter_server_mode):
    tool, stack = jupyter_server_mode
    manager = _enrolled_manager()
    kernel_manager = CulledKernelManager()

    for _ in range(2):
        await tool.execute(
            mode=ServerMode.JUPYTER_SERVER,
            kernel_manager=kernel_manager,
            notebook_manager=manager,
            cell_index=0,
        )

    assert kernel_manager.started_paths == ["notebook.ipynb"]
    assert stack.put_kernels == ["kernel-2", "kernel-2"]


@pytest.mark.asyncio
async def test_rebinding_updates_the_current_notebook_entry(jupyter_server_mode):
    tool, _ = jupyter_server_mode
    manager = _enrolled_manager()
    kernel_manager = CulledKernelManager()

    await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        kernel_manager=kernel_manager,
        notebook_manager=manager,
        cell_index=0,
    )

    assert [name for name, _ in manager] == ["default"]
    assert manager.get_notebook_path("default") == "notebook.ipynb"
    assert get_current_notebook_context(manager) == ("notebook.ipynb", "kernel-2")
