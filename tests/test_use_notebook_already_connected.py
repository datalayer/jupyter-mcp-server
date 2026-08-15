# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""What a second use_notebook on the same notebook is told.

The old reply was "already activated now. DO NOT REACTIVATE AGAIN." — a
refusal with no information. The caller's actual question was "what is this
notebook running on?", and — when a kernel_id rode along — "did it apply?".
Told neither, agents detached and reconnected notebooks to find out.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool


@pytest.fixture
def connected():
    """A notebook already connected and current, on a known backend.

    Configured for the datalayer provider — the deployment where this reply
    matters, and where the Jupyter connectivity prechecks rightly stay out of
    the way.
    """
    from jupyter_mcp_server.config import reset_config, set_config

    reset_config()
    set_config(document_provider="datalayer", sandbox_variant="datalayer")
    manager = NotebookManager()
    manager.add_notebook(
        "welcome", {"id": "sandbox-abc"}, server_url="http://x", path="nb.ipynb"
    )
    manager.set_current_notebook("welcome")
    yield manager
    reset_config()


async def _reuse(manager, **kwargs):
    return await UseNotebookTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=SimpleNamespace(),
        notebook_manager=manager,
        notebook_name="welcome",
        notebook_path="nb.ipynb",
        use_mode="connect",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_the_reply_names_the_backend(connected):
    reply = await _reuse(connected)
    assert "sandbox-abc" in reply
    assert "DO NOT" not in reply  # a refusal is not an answer


@pytest.mark.asyncio
async def test_a_passed_kernel_id_is_declared_ignored(connected):
    """Silently dropping an argument is how reattach loops start.

    The agent passed a sandbox id as kernel_id, got a generic refusal, and
    concluded it must detach and reconnect to apply it. Saying "not applied,
    and here is the supported way" ends the loop at one call.
    """
    reply = await _reuse(connected, kernel_id="4304d6ec")
    assert "not applied" in reply
    assert "use_sandbox" in reply
