# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""What an agent can *know* about sandbox attachment without experimenting.

Attachment is implicit — the first execution binds the active sandbox to the
notebook — and every fact established implicitly needs a place where it can be
read back. Without one, agents have detached and reconnected notebooks purely
to find out where their cells run, and then reported the answer as a guess.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jupyter_mcp_sandboxes.manager import CodeSandboxManager
from jupyter_mcp_sandboxes.tools import UseSandboxTool, _annotate_attached_notebooks


class TestListShowsAttachment:
    def test_a_bound_notebook_is_named_on_its_sandbox(self):
        from jupyter_mcp_server.notebook_manager import NotebookManager

        client = SimpleNamespace(is_alive=lambda: True)
        manager = CodeSandboxManager()
        manager._sandboxes["welcome-sandbox"] = client

        notebooks = NotebookManager()
        notebooks.add_notebook("welcome", client, server_url="x", path="p")

        sandboxes = [{"name": "welcome-sandbox"}]
        with patch("jupyter_mcp_server.server.notebook_manager", notebooks):
            _annotate_attached_notebooks(sandboxes, manager)
        assert sandboxes[0]["attached_notebooks"] == ["welcome"]

    def test_an_unbound_sandbox_says_so_explicitly(self):
        from jupyter_mcp_server.notebook_manager import NotebookManager

        manager = CodeSandboxManager()
        manager._sandboxes["idle-sandbox"] = SimpleNamespace()
        sandboxes = [{"name": "idle-sandbox"}]
        with patch("jupyter_mcp_server.server.notebook_manager", NotebookManager()):
            _annotate_attached_notebooks(sandboxes, manager)
        # An empty list is an answer; a missing key is a question.
        assert sandboxes[0]["attached_notebooks"] == []

    def test_a_failure_costs_the_extras_not_the_listing(self):
        sandboxes = [{"name": "s"}]
        _annotate_attached_notebooks(sandboxes, manager=None)  # blows up inside
        assert sandboxes[0]["name"] == "s"


class TestTheMessagesMatchTheRouting:
    @pytest.mark.asyncio
    async def test_use_sandbox_explains_cell_attachment(self):
        manager = CodeSandboxManager()
        manager._sandboxes["s1"] = SimpleNamespace()
        reply = await UseSandboxTool().execute(
            mode=None, code_sandbox_manager=manager, sandbox_name="s1"
        )
        # The old text said execute_code only; agents concluded execute_cell
        # was unrelated and tried to attach sandboxes as kernel ids.
        assert "execute_cell" in reply
        assert "kernel_id" not in reply
