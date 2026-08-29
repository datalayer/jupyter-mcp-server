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


class TestTheToolSurfaceIsProviderNeutral:
    """What the launch tool offers an agent, and what it deliberately does not.

    This extension can launch on a dozen backends, and its tool says so. What
    it must not carry is one provider's private plumbing: an argument that
    means something for exactly one backend is an argument every agent using
    every other backend has to read, understand and decline.

    `run_url` was that. It overrode the Datalayer run URL, and an operator
    pointing this server at Datalayer sets `--code-sandbox-url` instead —
    which the kernel factory already reads. So it was a Datalayer-only knob in
    a shared surface, redundant with configuration.
    """

    @staticmethod
    def _launch_arguments() -> set[str]:
        import inspect

        from jupyter_mcp_sandboxes.tools import LaunchSandboxTool

        return set(inspect.signature(LaunchSandboxTool.execute).parameters)

    def test_the_datalayer_run_url_override_is_gone(self):
        assert "run_url" not in self._launch_arguments()

    def test_the_arguments_every_provider_shares_are_kept(self):
        """`environment` and `gpu` are not Datalayer's: modal, daytona,
        coreweave and kaggle all take them, and `code_sandboxes` is where the
        answer about each lives."""
        assert {"environment", "gpu", "variant", "timeout"} <= self._launch_arguments()

    def test_the_datalayer_variant_still_works(self):
        """Reduced, not removed. `code_sandboxes` supports the variant, and a
        self-hosting user pointing this server at Datalayer is doing something
        the project supports — making it the one backend of twelve this tool
        could not reach would be a regression, not a tidy-up."""
        import inspect

        from jupyter_mcp_sandboxes.kernel import build_sandbox_client

        assert "datalayer" in inspect.getsource(build_sandbox_client)

    def test_the_token_argument_no_longer_claims_two_meanings(self):
        """It said "Datalayer API token override, or Kaggle API token". One
        argument meaning two unrelated things across two providers is one an
        agent cannot use correctly without knowing which backend it is on."""
        import inspect

        from jupyter_mcp_sandboxes import extension

        source = inspect.getsource(extension.SandboxesExtension.register_tools)
        assert "Datalayer API token override" not in source
