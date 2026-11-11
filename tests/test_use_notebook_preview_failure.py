# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""What use_notebook says when the notebook's preview cannot be loaded.

Since NotebookConnection.__aenter__ raises when the collaborative document
does not sync (e.g. a notebook larger than WEBSOCKETS_MAX_BODY_SIZE), the
preview block in use_notebook is the first place that error surfaces. It used
to be logged at debug level only, so use_notebook reported a plain success
and the error appeared on the next cell tool instead. The notebook stays
active (the preview is a courtesy), but the reply now carries the warning.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

SYNC_ERROR = "Notebook 'big.ipynb' did not sync: document exceeds WEBSOCKETS_MAX_BODY_SIZE"


@pytest.fixture
def manager():
    """Two connected notebooks, "first" current, on known backends.

    The datalayer provider keeps the Jupyter connectivity and path prechecks
    out of the way, as in test_use_notebook_already_connected.py.
    """
    from jupyter_mcp_server.config import reset_config, set_config

    reset_config()
    set_config(document_provider="datalayer", sandbox_variant="datalayer")
    nm = NotebookManager()
    nm.add_notebook("first", {"id": "sb-first"}, server_url="http://x", path="first.ipynb")
    nm.add_notebook("big", {"id": "sb-big"}, server_url="http://x", path="big.ipynb")
    nm.set_current_notebook("first")
    yield nm
    reset_config()


@pytest.mark.asyncio
async def test_a_failed_preview_is_reported_and_activation_stands(manager, monkeypatch):
    @asynccontextmanager
    async def failing_connection():
        raise RuntimeError(SYNC_ERROR)
        yield  # pragma: no cover

    monkeypatch.setattr(manager, "get_current_connection", failing_connection)

    reply = await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=SimpleNamespace(),
        notebook_manager=manager,
        notebook_name="big",
        notebook_path="big.ipynb",
        use_mode="connect",
    )

    assert "Reactivating notebook 'big'" in reply
    assert f"[WARNING] Could not load notebook preview: {SYNC_ERROR}" in reply
    assert manager.get_current_notebook() == "big"
