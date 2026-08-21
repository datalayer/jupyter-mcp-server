# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for code-sandboxes variant routing in the sandboxes extension."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jupyter_mcp_server.config import JupyterMCPConfig
from jupyter_mcp_server.tools._base import ServerMode

from jupyter_mcp_sandboxes.extension import SandboxesExtension
from jupyter_mcp_sandboxes.kernel import build_sandbox_client


@pytest.mark.parametrize(
    "engine,expected_variant",
    [
        ("eval", "eval"),
        ("docker", "docker"),
        ("monty", "monty"),
        ("modal", "modal"),
        ("daytona", "daytona"),
        ("e2b", "e2b"),
        ("coreweave", "coreweave"),
        ("cloudflare", "cloudflare"),
        ("datalayer", "datalayer"),
    ],
)
def test_build_sandbox_variant_routing(engine, expected_variant):
    """Generic sandbox engines are routed to Sandbox.create(variant=engine)."""
    config = JupyterMCPConfig(sandbox_variant=engine, sandbox_environment="ai-agents-env")

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == expected_variant
        assert kwargs["timeout"] == float(config.execution_timeout)


def test_build_sandbox_colab_forwards_code_sandbox_connection():
    """Colab engine forwards code sandbox URL, kernel id and proxy token."""
    config = JupyterMCPConfig(
        sandbox_variant="google-colab",
        code_sandbox_url="https://colab-host.example",
        code_sandbox_id="kernel-id",
        code_sandbox_proxy_token="proxy-token",
    )

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        mock_create.assert_called_once_with(
            variant="google-colab",
            timeout=float(config.execution_timeout),
            server_url="https://colab-host.example",
            kernel_id="kernel-id",
            proxy_token="proxy-token",
        )


def test_build_sandbox_colab_forwards_channels_url_without_kernel_id():
    """Colab engine forwards channels_url when supplied and allows missing kernel_id."""
    config = JupyterMCPConfig(
        sandbox_variant="google-colab",
        code_sandbox_url="https://colab-host.example",
        code_sandbox_proxy_token="proxy-token",
        code_sandbox_channels_url=(
            "wss://colab-host.example/api/kernels/"
            "11e073f0-e82d-4029-be8d-3918f7ed1a9e/channels"
            "?session_id=abc&colab-runtime-proxy-token=proxy-token"
        ),
    )

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "google-colab"
        assert kwargs["server_url"] == "https://colab-host.example"
        assert kwargs["proxy_token"] == "proxy-token"
        assert "kernel_id" not in kwargs
        assert kwargs["channels_url"].startswith("wss://colab-host.example")


def test_build_sandbox_kaggle_forwards_code_sandbox_connection_and_token():
    """Kaggle engine forwards code sandbox URL, optional kernel id and token."""
    config = JupyterMCPConfig(
        sandbox_variant="kaggle",
        code_sandbox_url="https://kaggle-host.example/proxy",
        code_sandbox_id="kernel-id",
        code_sandbox_token="kaggle-token",
    )

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

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

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert kwargs["gpu"] == "T4"


def test_build_sandbox_kaggle_forwards_channels_url_without_kernel_id():
    """Kaggle engine forwards channels_url when supplied and allows missing kernel_id."""
    config = JupyterMCPConfig(
        sandbox_variant="kaggle",
        code_sandbox_url="https://kaggle-host.example/proxy",
        code_sandbox_channels_url=(
            "wss://kaggle-host.example/k/123/proxy/api/kernels/"
            "11e073f0-e82d-4029-be8d-3918f7ed1a9e/channels?session_id=abc"
        ),
    )

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert "server_url" not in kwargs
        assert "kernel_id" not in kwargs
        assert kwargs["channels_url"].startswith("wss://kaggle-host.example")


def test_build_sandbox_kaggle_defaults_to_batch_when_code_sandbox_not_configured():
    """Kaggle engine should prefer batch mode when code sandbox values are not explicitly set."""
    config = JupyterMCPConfig(sandbox_variant="kaggle")

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert "server_url" not in kwargs
        assert "kernel_id" not in kwargs
        assert "channels_url" not in kwargs


def test_build_sandbox_kaggle_channels_url_ignores_default_code_sandbox_url():
    """When channels_url is set, default localhost code sandbox URL must not leak into Kaggle create args."""
    config = JupyterMCPConfig(
        sandbox_variant="kaggle",
        code_sandbox_channels_url=(
            "wss://kaggle-host.example/k/123/proxy/api/kernels/"
            "11e073f0-e82d-4029-be8d-3918f7ed1a9e/channels?session_id=abc"
        ),
    )

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "kaggle"
        assert "server_url" not in kwargs
        assert kwargs["channels_url"].startswith("wss://kaggle-host.example")


def test_build_sandbox_datalayer_forwards_token_and_run_url():
    """Datalayer engine forwards code sandbox auth/settings to code-sandboxes."""
    config = JupyterMCPConfig(
        sandbox_variant="datalayer",
        code_sandbox_url="https://run.example",
        code_sandbox_token="api-token",
        sandbox_environment="ai-agents-env",
    )

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

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

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "modal"
        assert kwargs["gpu"] == "A100"


@pytest.mark.parametrize("engine", ["daytona", "coreweave"])
def test_build_sandbox_forwards_gpu_flavor_for_gpu_engines(engine):
    """Daytona and CoreWeave run on GPUs, so SANDBOX_GPU reaches them."""
    config = JupyterMCPConfig(sandbox_variant=engine, sandbox_gpu="H100")

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == engine
        assert kwargs["gpu"] == "H100"


@pytest.mark.parametrize("engine", ["e2b", "cloudflare"])
def test_build_sandbox_omits_gpu_flavor_for_engines_without_one(engine):
    """E2B and Cloudflare offer no GPU, so the flavor is not passed as if they did."""
    config = JupyterMCPConfig(sandbox_variant=engine, sandbox_gpu="H100")

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == engine
        assert "gpu" not in kwargs


def test_build_sandbox_jupyter_forwards_code_sandbox_and_reconnect():
    """Jupyter engine forwards code sandbox connection settings and disables implicit reuse."""
    config = JupyterMCPConfig(
        sandbox_variant="jupyter-server",
        code_sandbox_url="https://jupyter-host.example",
        code_sandbox_token="code-sandbox-token",
        code_sandbox_id="kernel-id",
        reconnect_interval=5,
    )

    with patch("code_sandboxes.CodeSandboxClient.create") as mock_create:
        mock_create.return_value = MagicMock()

        build_sandbox_client(config, MagicMock())

        mock_create.assert_called_once_with(
            variant="jupyter-server",
            timeout=float(config.execution_timeout),
            server_url="https://jupyter-host.example",
            token="code-sandbox-token",
            kernel_id="kernel-id",
            reuse_kernel=False,
            client_kwargs={"reconnect_interval": 5},
        )


def test_extension_create_kernel_returns_none_for_jupyter_variant():
    """The default jupyter variant is handled by the core, not the extension."""
    config = JupyterMCPConfig(sandbox_variant="jupyter-server")
    extension = SandboxesExtension()

    assert extension.create_code_sandbox(config, MagicMock()) is None


def test_extension_create_kernel_uses_code_sandbox_client_for_sandbox_engines():
    """Non-jupyter sandbox variants must return the sandbox's plain code sandbox client."""
    config = JupyterMCPConfig(
        sandbox_variant="docker",
        code_sandbox_url="http://localhost:8888",
    )
    fake_sandbox_client = MagicMock()
    extension = SandboxesExtension()

    with patch(
        "jupyter_mcp_sandboxes.kernel.create_sandbox_client",
        return_value=fake_sandbox_client,
    ) as mock_create_client:
        kernel = extension.create_code_sandbox(config, MagicMock())

    assert kernel is fake_sandbox_client
    mock_create_client.assert_called_once()


def test_extension_create_kernel_builds_and_starts_sandbox_client():
    """create_code_sandbox builds, starts, and returns a CodeSandboxClient."""
    config = JupyterMCPConfig(
        sandbox_variant="docker",
        code_sandbox_url="https://run.example",
    )
    fake_logger = MagicMock()
    fake_sandbox_client = MagicMock()
    extension = SandboxesExtension()

    with patch(
        "code_sandboxes.CodeSandboxClient.create",
        return_value=fake_sandbox_client,
    ) as mock_create:
        kernel = extension.create_code_sandbox(config, fake_logger)

    assert kernel is fake_sandbox_client
    mock_create.assert_called_once()
    fake_sandbox_client.start.assert_called_once_with()


def test_extension_returns_managed_sandbox_client():
    """The extension returns the managed client without exposing its backend."""
    config = JupyterMCPConfig(sandbox_variant="docker")
    fake_logger = MagicMock()
    fake_sandbox_client = MagicMock()
    extension = SandboxesExtension()

    with patch(
        "code_sandboxes.CodeSandboxClient.create",
        return_value=fake_sandbox_client,
    ):
        kernel = extension.create_code_sandbox(config, fake_logger)

    assert kernel is fake_sandbox_client
    kernel.stop()
    fake_sandbox_client.stop.assert_called_once_with()


def test_extension_create_kernel_supports_non_kernel_variant():
    """Notebook-bound execution accepts every CodeSandboxClient variant."""
    config = JupyterMCPConfig(sandbox_variant="eval")
    fake_logger = MagicMock()
    fake_sandbox_client = MagicMock()
    extension = SandboxesExtension()

    with patch(
        "code_sandboxes.CodeSandboxClient.create",
        return_value=fake_sandbox_client,
    ):
        kernel = extension.create_code_sandbox(config, fake_logger)

    assert kernel is fake_sandbox_client
    fake_sandbox_client.start.assert_called_once_with()


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
            return_value=JupyterMCPConfig(sandbox_variant="jupyter-server"),
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


@pytest.mark.asyncio
async def test_launch_sandbox_kaggle_variant_forwards_code_sandbox_fields():
    extension = SandboxesExtension()
    mcp = _FakeMCP()
    fake_context = type("FakeContext", (), {"mode": ServerMode.MCP_SERVER})()

    with (
        patch("jupyter_mcp_sandboxes.extension.ServerContext.get_instance", return_value=fake_context),
        patch(
            "jupyter_mcp_sandboxes.extension.get_config",
            return_value=JupyterMCPConfig(sandbox_variant="jupyter-server"),
        ),
        patch(
            "jupyter_mcp_sandboxes.extension.LaunchSandboxTool.execute",
            new_callable=AsyncMock,
            return_value={"message": "ok", "sandbox": {}},
        ) as mock_execute,
    ):
        extension.register_tools(mcp)
        await mcp.tools["launch_sandbox"](
            sandbox_name="kaggle-sbx",
            variant="kaggle",
            server_url="https://kaggle.example/proxy",
            kernel_id="k-123",
            channels_url="wss://kaggle.example/channels",
            token="kaggle-token",
            gpu="T4",
        )

    kwargs = mock_execute.await_args.kwargs
    assert kwargs["variant"] == "kaggle"
    assert kwargs["server_url"] == "https://kaggle.example/proxy"
    assert kwargs["kernel_id"] == "k-123"
    assert kwargs["channels_url"] == "wss://kaggle.example/channels"
    assert kwargs["token"] == "kaggle-token"
    assert kwargs["gpu"] == "T4"
