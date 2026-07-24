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
        )


def test_build_sandbox_colab_forwards_channels_url_without_kernel_id():
    """Colab engine forwards channels_url when supplied and allows missing kernel_id."""
    config = JupyterMCPConfig(
        sandbox_variant="colab",
        runtime_url="https://colab-host.example",
        runtime_proxy_token="proxy-token",
        runtime_channels_url=(
            "wss://colab-host.example/api/kernels/"
            "11e073f0-e82d-4029-be8d-3918f7ed1a9e/channels"
            "?session_id=abc&colab-runtime-proxy-token=proxy-token"
        ),
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "colab"
        assert kwargs["server_url"] == "https://colab-host.example"
        assert kwargs["proxy_token"] == "proxy-token"
        assert "kernel_id" not in kwargs
        assert kwargs["channels_url"].startswith("wss://colab-host.example")


def test_build_sandbox_kaggle_forwards_runtime_connection_and_token():
    """Kaggle engine forwards runtime URL, optional kernel id and token."""
    config = JupyterMCPConfig(
        sandbox_variant="kaggle",
        runtime_url="https://kaggle-host.example/proxy",
        runtime_id="kernel-id",
        runtime_token="kaggle-token",
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert kwargs["server_url"] == "https://kaggle-host.example/proxy"
        assert kwargs["kernel_id"] == "kernel-id"
        assert kwargs["token"] == "kaggle-token"


def test_build_sandbox_kaggle_forwards_gpu_flavor():
    """Kaggle engine forwards SANDBOX_GPU as a batch accelerator hint."""
    config = JupyterMCPConfig(
        sandbox_variant="kaggle",
        sandbox_gpu="T4",
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert kwargs["gpu"] == "T4"


def test_build_sandbox_kaggle_forwards_channels_url_without_kernel_id():
    """Kaggle engine forwards channels_url when supplied and allows missing kernel_id."""
    config = JupyterMCPConfig(
        sandbox_variant="kaggle",
        runtime_url="https://kaggle-host.example/proxy",
        runtime_channels_url=(
            "wss://kaggle-host.example/k/123/proxy/api/kernels/"
            "11e073f0-e82d-4029-be8d-3918f7ed1a9e/channels?session_id=abc"
        ),
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert "server_url" not in kwargs
        assert "kernel_id" not in kwargs
        assert kwargs["channels_url"].startswith("wss://kaggle-host.example")


def test_build_sandbox_kaggle_defaults_to_batch_when_runtime_not_configured():
    """Kaggle engine should prefer batch mode when runtime values are not explicitly set."""
    config = JupyterMCPConfig(sandbox_variant="kaggle")

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert "server_url" not in kwargs
        assert "kernel_id" not in kwargs
        assert "channels_url" not in kwargs


def test_build_sandbox_kaggle_channels_url_ignores_default_runtime_url():
    """When channels_url is set, default localhost runtime URL must not leak into Kaggle create args."""
    config = JupyterMCPConfig(
        sandbox_variant="kaggle",
        runtime_channels_url=(
            "wss://kaggle-host.example/k/123/proxy/api/kernels/"
            "11e073f0-e82d-4029-be8d-3918f7ed1a9e/channels?session_id=abc"
        ),
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert "server_url" not in kwargs
        assert kwargs["channels_url"].startswith("wss://kaggle-host.example")


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
