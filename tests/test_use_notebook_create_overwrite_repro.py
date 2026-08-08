# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Repro: use_notebook(use_mode="create") against a REAL jupyter_server
contents manager silently overwrites an existing notebook file on disk.

Unlike test_use_notebook_create_local.py's RecordingContentsManager (which
always reports an empty directory), this drives UseNotebookTool against
jupyter_server's own AsyncFileContentsManager pointed at a real temp
directory, so the file-exists / overwrite semantics are the production
manager's, not a stand-in's.
"""

import tempfile
from pathlib import Path

import nbformat
import pytest
from jupyter_server.services.contents.filemanager import AsyncFileContentsManager

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool


class RecordingKernelManager:
    async def start_kernel(self):
        return "kernel-1"

    def get_kernel(self, kernel_id):
        return object()

    def get_connection_info(self, kernel_id):
        return {"shell_port": 1}


class RecordingSessionManager:
    async def create_session(self, path=None, kernel_id=None, type=None, name=None):
        return {"id": "session-1"}


@pytest.mark.asyncio
async def test_create_mode_overwrites_an_existing_notebook_on_real_contents_manager():
    """A second, independent use_notebook(use_mode="create") call at a path
    that already holds real work must not destroy it."""
    with tempfile.TemporaryDirectory() as root_dir:
        contents_manager = AsyncFileContentsManager(root_dir=root_dir)

        # Simulate a notebook that already has real user work in it, written
        # directly (as an earlier session's use_notebook(create) call would
        # have done via this exact tool).
        real_work = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("df = load_customer_data()  # 3 hours of work")]
        )
        (Path(root_dir) / "analysis.ipynb").write_text(nbformat.writes(real_work))

        # A second, independent client (fresh NotebookManager => tool has no
        # record of "analysis" being in use) calls use_notebook(create) at
        # the SAME path.
        await UseNotebookTool().execute(
            mode=ServerMode.JUPYTER_SERVER,
            contents_manager=contents_manager,
            kernel_manager=RecordingKernelManager(),
            session_manager=RecordingSessionManager(),
            notebook_manager=NotebookManager(),
            notebook_name="analysis_second_client",
            notebook_path="analysis.ipynb",
            use_mode="create",
        )

        on_disk = nbformat.reads((Path(root_dir) / "analysis.ipynb").read_text(), as_version=4)
        assert on_disk.cells[0].source == "df = load_customer_data()  # 3 hours of work", (
            "use_notebook(create) silently overwrote an existing notebook: "
            f"cells on disk are now {[c.source for c in on_disk.cells]!r}"
        )
