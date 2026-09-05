# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# Datalayer License

"""A sandbox this server did not launch can be used by name."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jupyter_mcp_sandboxes.manager import CodeSandboxManager
from jupyter_mcp_sandboxes.tools import UseSandboxTool


def _sandbox(sandbox_id="rt-1"):
    sandbox = MagicMock()
    sandbox.id = sandbox_id
    sandbox.info = SimpleNamespace(variant="datalayer", status="running")
    sandbox.config = SimpleNamespace(environment="python-cpu-env", gpu=None)
    sandbox.is_started = True
    return sandbox


class TestAttach:
    def test_a_datalayer_sandbox_is_borrowed_by_name(self):
        manager = CodeSandboxManager()
        with patch("code_sandboxes.datalayer_sandbox.DatalayerSandbox.from_id", return_value=_sandbox()) as from_id:
            answer = manager.attach("rt-1", token="tok", run_url="https://run")
        from_id.assert_called_once_with("rt-1", token="tok", run_url="https://run")
        assert answer["name"] == "rt-1" and answer["active"] is True
        assert manager.use("rt-1") == "rt-1"

    def test_terminating_a_borrowed_sandbox_leaves_it_running(self):
        manager = CodeSandboxManager()
        sandbox = _sandbox()
        with patch("code_sandboxes.datalayer_sandbox.DatalayerSandbox.from_id", return_value=sandbox):
            manager.attach("rt-1")
        client = manager._sandboxes["rt-1"]
        assert client._owns_sandbox is False, "a borrowed sandbox is not this server's to stop"

    def test_attaching_twice_is_the_same_sandbox(self):
        manager = CodeSandboxManager()
        with patch("code_sandboxes.datalayer_sandbox.DatalayerSandbox.from_id", return_value=_sandbox()) as from_id:
            manager.attach("rt-1")
            manager.attach("rt-1")
        assert from_id.call_count == 1

    def test_only_datalayer_can_be_attached(self):
        with pytest.raises(ValueError, match="only 'datalayer'"):
            CodeSandboxManager().attach("x", variant="e2b")


@pytest.mark.asyncio
class TestUseSandboxReachesForIt:
    async def test_an_unknown_name_is_attached(self):
        manager = CodeSandboxManager()
        with patch(
            "code_sandboxes.datalayer_sandbox.DatalayerSandbox.from_id", return_value=_sandbox()
        ) as from_id:
            answer = await UseSandboxTool().execute(mode=None, code_sandbox_manager=manager, sandbox_name="rt-1")
        # The message alone would pass if the tool never reached for the
        # sandbox at all, which is the whole of what this test is about —
        # its sibling below asserts the other direction.
        from_id.assert_called_once_with("rt-1", token=None, run_url=None)
        assert "Sandbox 'rt-1' is now active" in answer

    async def test_a_name_nobody_knows_is_said_so(self):
        manager = CodeSandboxManager()
        from code_sandboxes.datalayer_sandbox import SandboxNotFoundError

        with patch("code_sandboxes.datalayer_sandbox.DatalayerSandbox.from_id", side_effect=SandboxNotFoundError("nope")):
            with pytest.raises(ValueError, match="could not be reached by name"):
                await UseSandboxTool().execute(mode=None, code_sandbox_manager=manager, sandbox_name="nope")

    async def test_clearing_the_selection_never_attaches(self):
        manager = CodeSandboxManager()
        with patch("code_sandboxes.datalayer_sandbox.DatalayerSandbox.from_id") as from_id:
            answer = await UseSandboxTool().execute(mode=None, code_sandbox_manager=manager, sandbox_name=None)
        assert "disabled" in answer and from_id.call_count == 0
