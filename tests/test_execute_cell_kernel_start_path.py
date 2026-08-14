# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression test for local kernel reprovisioning working directories."""

from pathlib import Path
from types import SimpleNamespace

import nbformat
import pytest

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool


class RecordingKernelManager:
    """Minimal local kernel manager that records the requested working directory."""

    def __init__(self):
        self.started_paths = []

    async def start_kernel(self, path=None):
        self.started_paths.append(path)
        return "kernel-1"


class FileIdManager:
    def __init__(self):
        self.paths = []

    def get_id(self, path):
        self.paths.append(path)
        return "file-id"

    def index(self, _path):
        return "file-id"


@pytest.mark.asyncio
async def test_reprovisioned_kernel_uses_notebook_api_path_not_absolute_file_path(monkeypatch):
    """A replacement kernel receives the root-relative Jupyter notebook path."""
    async def no_sleep(_seconds):
        return None

    async def no_ydoc(_serverapp, _file_id):
        return None

    async def no_outputs(*_args, **_kwargs):
        return None

    async def empty_execution(**_kwargs):
        return []

    read_paths = []

    async def read_notebook(path):
        read_paths.append(path)
        return nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("1 + 1")])

    file_id_manager = FileIdManager()
    serverapp = SimpleNamespace(
        root_dir="/srv/notebooks",
        web_app=SimpleNamespace(settings={"file_id_manager": file_id_manager}),
    )
    monkeypatch.setattr(
        "jupyter_mcp_server.jupyter_extension.context.get_server_context",
        lambda: SimpleNamespace(serverapp=serverapp),
    )
    monkeypatch.setattr(
        "jupyter_mcp_server.tools.execute_cell_tool.get_current_notebook_context",
        lambda _manager: ("projects/demo/notebook.ipynb", None),
    )
    monkeypatch.setattr("jupyter_mcp_server.tools.execute_cell_tool.asyncio.sleep", no_sleep)
    monkeypatch.setattr("jupyter_mcp_server.tools.execute_cell_tool.get_jupyter_ydoc", no_ydoc)
    monkeypatch.setattr(
        "jupyter_mcp_server.tools.execute_cell_tool.execute_via_execution_stack",
        empty_execution,
    )
    monkeypatch.setattr(ExecuteCellTool, "_write_outputs_to_cell", no_outputs)

    tool = ExecuteCellTool()
    monkeypatch.setattr(
        tool,
        "_read_notebook_file_with_retry",
        read_notebook,
    )
    kernel_manager = RecordingKernelManager()

    await tool.execute(
        mode=ServerMode.JUPYTER_SERVER,
        kernel_manager=kernel_manager,
        notebook_manager=NotebookManager(),
        cell_index=0,
    )

    assert kernel_manager.started_paths == ["projects/demo/notebook.ipynb"]
    filesystem_notebook_path = str(
        Path("/srv/notebooks") / "projects/demo/notebook.ipynb"
    )
    assert file_id_manager.paths == [filesystem_notebook_path]
    assert read_paths == [filesystem_notebook_path]
