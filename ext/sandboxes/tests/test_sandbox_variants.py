# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for code-sandboxes variant routing in the sandboxes extension."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jupyter_mcp_server.config import JupyterMCPConfig
from jupyter_mcp_server.tools._base import ServerMode

from jupyter_mcp_sandboxes.extension import SandboxesExtension
from jupyter_mcp_sandboxes.kernel import build_sandbox


@pytest.mark.parametrize(
    "engine,expected_variant",
    [
        ("eval", "eval"),
        ("docker", "docker"),
        ("monty", "monty"),
        ("modal", "modal"),
        ("datalayer", "datalayer"),
    ],
)
def test_build_sandbox_variant_routing(engine, expected_variant):
    """Generic sandbox engines are routed to Sandbox.create(variant=engine)."""
    config = JupyterMCPConfig(sandbox_variant=engine, sandbox_environment="ai-agents-env")

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == expected_variant
        assert kwargs["timeout"] == float(config.execution_timeout)


def test_build_sandbox_colab_forwards_runtime_connection():
    """Colab engine forwards runtime URL, kernel id and proxy token."""
    config = JupyterMCPConfig(
        sandbox_variant="colab",
        runtime_url="https://colab-host.example",
        runtime_id="kernel-id",
        runtime_proxy_token="proxy-token",
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        mock_create.assert_called_once_with(
            variant="colab",
            timeout=float(config.execution_timeout),
            server_url="https://colab-host.example",
            kernel_id="kernel-id",
            proxy_token="proxy-token",
            use_browser_bridge=False,
        )


def test_build_sandbox_colab_enables_browser_bridge():
    """Colab engine forwards the browser-bridge flag to code-sandboxes."""
    config = JupyterMCPConfig(
        sandbox_variant="colab",
        runtime_use_browser_bridge=True,
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        _, kwargs = mock_create.call_args
        assert kwargs["variant"] == "colab"
        assert kwargs["use_browser_bridge"] is True


def test_build_sandbox_datalayer_forwards_token_and_run_url():
    """Datalayer engine forwards runtime auth/settings to code-sandboxes."""
    config = JupyterMCPConfig(
        sandbox_variant="datalayer",
        runtime_url="https://run.example",
        runtime_token="api-token",
        sandbox_environment="ai-agents-env",
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "datalayer"
        assert kwargs["token"] == "api-token"
        assert kwargs["run_url"] == "https://run.example"
        assert kwargs["environment"] == "ai-agents-env"


def test_build_sandbox_modal_forwards_gpu_flavor():
    """Modal engine forwards SANDBOX_GPU to code-sandboxes."""
    config = JupyterMCPConfig(
        sandbox_variant="modal",
        sandbox_gpu="A100",
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "modal"
        assert kwargs["gpu"] == "A100"


def test_extension_create_kernel_returns_none_for_jupyter_variant():
    """The default jupyter variant is handled by the core, not the extension."""
    config = JupyterMCPConfig(sandbox_variant="jupyter")
    extension = SandboxesExtension()

    assert extension.create_kernel(config, MagicMock()) is None


def test_extension_create_kernel_uses_sandbox_kernel_for_sandbox_engines():
    """Non-jupyter sandbox variants must use the SandboxKernel wrapper."""
    config = JupyterMCPConfig(
        sandbox_variant="datalayer",
        runtime_url="http://localhost:8888",
    )
    fake_sandbox = MagicMock()
    fake_kernel = MagicMock()
    extension = SandboxesExtension()

    with (
        patch("jupyter_mcp_sandboxes.kernel.build_sandbox", return_value=fake_sandbox),
        patch("jupyter_mcp_sandboxes.kernel.SandboxKernel", return_value=fake_kernel),
    ):
        kernel = extension.create_kernel(config, MagicMock())

    assert kernel is fake_kernel
    fake_kernel.start.assert_called_once_with()


def test_extension_create_kernel_builds_and_starts_kernel():
    """create_kernel uses Sandbox.create via build_sandbox and starts SandboxKernel."""
    config = JupyterMCPConfig(
        sandbox_variant="datalayer",
        runtime_url="https://run.example",
    )
    fake_logger = MagicMock()
    fake_sandbox = MagicMock()
    fake_kernel = MagicMock()
    extension = SandboxesExtension()

    with (
        patch("code_sandboxes.Sandbox.create", return_value=fake_sandbox) as mock_create,
        patch(
            "jupyter_mcp_sandboxes.kernel.SandboxKernel", return_value=fake_kernel
        ) as mock_wrapper,
    ):
        kernel = extension.create_kernel(config, fake_logger)

    assert kernel is fake_kernel
    mock_create.assert_called_once()
    mock_wrapper.assert_called_once_with(fake_sandbox, logger=fake_logger)
    fake_kernel.start.assert_called_once_with()


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, **_kwargs):
        def _decorator(func):
            self.tools[func.__name__] = func
            return func

        return _decorator


@pytest.mark.asyncio
async def test_launch_sandbox_defaults_to_configured_non_jupyter_variant():
    extension = SandboxesExtension()
    mcp = _FakeMCP()
    fake_context = type("FakeContext", (), {"mode": ServerMode.MCP_SERVER})()

    with (
        patch("jupyter_mcp_sandboxes.extension.ServerContext.get_instance", return_value=fake_context),
        patch(
            "jupyter_mcp_sandboxes.extension.get_config",
            return_value=JupyterMCPConfig(sandbox_variant="monty"),
        ),
        patch(
            "jupyter_mcp_sandboxes.extension.LaunchSandboxTool.execute",
            new_callable=AsyncMock,
            return_value={"message": "ok", "sandbox": {}},
        ) as mock_execute,
    ):
        extension.register_tools(mcp)
        await mcp.tools["launch_sandbox"](sandbox_name="my_sandbox")

    assert mock_execute.await_args.kwargs["variant"] == "monty"


@pytest.mark.asyncio
async def test_launch_sandbox_defaults_to_eval_for_jupyter_configured_variant():
    extension = SandboxesExtension()
    mcp = _FakeMCP()
    fake_context = type("FakeContext", (), {"mode": ServerMode.MCP_SERVER})()

    with (
        patch("jupyter_mcp_sandboxes.extension.ServerContext.get_instance", return_value=fake_context),
        patch(
            "jupyter_mcp_sandboxes.extension.get_config",
            return_value=JupyterMCPConfig(sandbox_variant="jupyter"),
        ),
        patch(
            "jupyter_mcp_sandboxes.extension.LaunchSandboxTool.execute",
            new_callable=AsyncMock,
            return_value={"message": "ok", "sandbox": {}},
        ) as mock_execute,
    ):
        extension.register_tools(mcp)
        await mcp.tools["launch_sandbox"](sandbox_name="my_sandbox")

    assert mock_execute.await_args.kwargs["variant"] == "eval"
