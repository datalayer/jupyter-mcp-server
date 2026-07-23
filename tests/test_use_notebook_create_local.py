# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for use_notebook(use_mode="create") in JUPYTER_SERVER mode.

These tests drive UseNotebookTool with in-memory stand-ins for the local
contents/kernel/session managers, so no running Jupyter server is required.
They cover what the tool asks those managers to do, and in which order, not the
behaviour the managers themselves implement.
"""

import pytest

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool


class RecordingContentsManager:
    """Stand-in for jupyter_server's ContentsManager that records the model it
    is asked to create instead of writing a file."""

    def __init__(self, events):
        self.events = events
        self.new_calls = []

    async def get(self, path, content=True, type=None):
        return {"content": []}

    async def new(self, model=None, path=""):
        self.events.append("new")
        self.new_calls.append((model, path))
        return {"path": path}


class RecordingKernelManager:
    """Stand-in for the local MultiKernelManager surface use_notebook touches."""

    def __init__(self, events):
        self.events = events

    async def start_kernel(self, kernel_name=None):
        self.events.append("start_kernel")
        return "kernel-1"

    def get_kernel(self, kernel_id):
        return object()

    def get_connection_info(self, kernel_id):
        return {"shell_port": 1}


class RecordingSessionManager:
    """Stand-in for jupyter_server's SessionManager."""

    def __init__(self, events):
        self.events = events

    async def create_session(self, path=None, kernel_id=None, type=None, name=None):
        self.events.append("create_session")
        return {"id": "session-1"}


async def _create_notebook():
    """Create 'nb.ipynb' over the JUPYTER_SERVER path, returning the recorded
    manager events and the contents_manager that saw the create call."""
    events = []
    contents_manager = RecordingContentsManager(events)
    await UseNotebookTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        contents_manager=contents_manager,
        kernel_manager=RecordingKernelManager(events),
        session_manager=RecordingSessionManager(events),
        notebook_manager=NotebookManager(),
        notebook_name="nb",
        notebook_path="nb.ipynb",
        use_mode="create",
    )
    return events, contents_manager


@pytest.mark.asyncio
async def test_create_passes_the_skeleton_to_the_contents_manager():
    """The notebook skeleton use_notebook builds must reach the local contents
    manager, so that creating a notebook produces the same file in
    JUPYTER_SERVER mode as it does over HTTP in MCP_SERVER mode."""
    _events, contents_manager = await _create_notebook()

    assert len(contents_manager.new_calls) == 1
    model, path = contents_manager.new_calls[0]
    assert path == "nb.ipynb"
    assert model["type"] == "notebook"
    assert model["content"]["cells"][0]["cell_type"] == "markdown"


@pytest.mark.asyncio
async def test_create_writes_the_notebook_before_starting_a_session_on_it():
    """A Jupyter session must never be created for a notebook path that does
    not exist yet, so the file is written before the kernel and session that
    point at it."""
    events, _contents_manager = await _create_notebook()

    assert events.index("new") < events.index("create_session")
    assert events.index("new") < events.index("start_kernel")
