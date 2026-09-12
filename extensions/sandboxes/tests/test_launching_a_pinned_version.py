# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Launching a named version of an environment (PLAN_ENV.md, D-2, E1-19).

An agent that was told to work in `ada/geo` version 3 has to get version 3,
not whatever its owner promoted since. The version travels from the MCP tool
through `LaunchSandboxTool` and the manager to `CodeSandboxClient.create`,
unchanged and in the type it arrived as — the platform reads a number as a
version number and a string as a version uid, so the two cannot be conflated
on the way.

Only the Datalayer variant has versions. Naming one for any other variant is
refused by name rather than dropped, for the reason pinning exists: a run that
silently took the provider's latest image would be unreproducible and nobody
would know.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jupyter_mcp_server.config import JupyterMCPConfig
from jupyter_mcp_server.tools._base import ServerMode

from jupyter_mcp_sandboxes.extension import SandboxesExtension
from jupyter_mcp_sandboxes.manager import CodeSandboxManager
from jupyter_mcp_sandboxes.tools import LaunchSandboxTool


@pytest.fixture
def fake_sandbox() -> MagicMock:
    sandbox = MagicMock()
    sandbox.id = "sandbox-id"
    sandbox.info = SimpleNamespace(variant="datalayer", status="running")
    sandbox.config = SimpleNamespace(environment="ada/geo", gpu=None)
    return sandbox


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, **_kwargs):
        def _decorator(func):
            self.tools[func.__name__] = func
            return func

        return _decorator


@pytest.mark.asyncio
async def test_the_mcp_tool_forwards_the_version_it_was_given():
    extension = SandboxesExtension()
    mcp = _FakeMCP()
    fake_context = type("FakeContext", (), {"mode": ServerMode.MCP_SERVER})()

    with (
        patch(
            "jupyter_mcp_sandboxes.extension.ServerContext.get_instance",
            return_value=fake_context,
        ),
        patch(
            "jupyter_mcp_sandboxes.extension.get_config",
            return_value=JupyterMCPConfig(sandbox_variant="datalayer"),
        ),
        patch(
            "jupyter_mcp_sandboxes.extension.LaunchSandboxTool.execute",
            new_callable=AsyncMock,
            return_value={"message": "ok", "sandbox": {}},
        ) as mock_execute,
    ):
        extension.register_tools(mcp)
        await mcp.tools["launch_sandbox"](
            sandbox_name="geo-sbx",
            environment="ada/geo",
            environment_version=3,
        )

    kwargs = mock_execute.await_args.kwargs
    assert kwargs["environment"] == "ada/geo"
    assert kwargs["environment_version"] == 3


@pytest.mark.asyncio
async def test_the_tool_hands_the_version_to_the_manager():
    manager = MagicMock()
    manager.launch.return_value = {"name": "geo-sbx"}

    answer = await LaunchSandboxTool().execute(
        mode=ServerMode.MCP_SERVER,
        code_sandbox_manager=manager,
        sandbox_name="geo-sbx",
        variant="datalayer",
        environment="ada/geo",
        environment_version="01VERSION",
    )

    assert manager.launch.call_args.kwargs["environment_version"] == "01VERSION"
    assert answer["sandbox"] == {"name": "geo-sbx"}


@pytest.mark.parametrize("version", [3, "01VERSION"])
def test_the_manager_pins_the_version_in_the_type_it_arrived_as(
    version: int | str, fake_sandbox: MagicMock
):
    manager = CodeSandboxManager()

    with patch(
        "code_sandboxes.CodeSandboxClient.create", return_value=fake_sandbox
    ) as mock_create:
        manager.launch(
            sandbox_name="geo-sbx",
            variant="datalayer",
            timeout=60,
            environment="ada/geo",
            environment_version=version,
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["environment"] == "ada/geo"
    assert kwargs["environment_version"] == version
    assert type(kwargs["environment_version"]) is type(version)


@pytest.mark.parametrize("version", [None, "", "   "])
def test_no_version_asks_for_none_and_gets_the_promoted_one(
    version: str | None, fake_sandbox: MagicMock
):
    """Blank reads as unset, as an empty `environment` and `gpu` do: the hosted
    gateway turns absent arguments into empty strings, and a sandbox launched
    that way should run the promoted version rather than one called "  "."""
    manager = CodeSandboxManager()

    with patch(
        "code_sandboxes.CodeSandboxClient.create", return_value=fake_sandbox
    ) as mock_create:
        manager.launch(
            sandbox_name="geo-sbx",
            variant="datalayer",
            timeout=60,
            environment="ada/geo",
            environment_version=version,
        )

    assert "environment_version" not in mock_create.call_args.kwargs


@pytest.mark.parametrize("variant", ["modal", "daytona", "e2b", "eval"])
def test_a_version_named_for_a_variant_without_versions_is_refused(
    variant: str, fake_sandbox: MagicMock
):
    manager = CodeSandboxManager()

    with patch(
        "code_sandboxes.CodeSandboxClient.create", return_value=fake_sandbox
    ) as mock_create:
        with pytest.raises(ValueError, match="no environment versions"):
            manager.launch(
                sandbox_name="geo-sbx",
                variant=variant,
                timeout=60,
                environment="ada/geo",
                environment_version=3,
            )

    mock_create.assert_not_called()
    assert manager.list() == []
