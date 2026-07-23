# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tests for code-sandboxes engine routing in jupyter-mcp-server."""

from unittest.mock import MagicMock, patch

import pytest

from jupyter_mcp_server.config import JupyterMCPConfig
from jupyter_mcp_server.utils import _build_sandbox, create_kernel


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
    config = JupyterMCPConfig(execution_engine=engine, sandbox_environment="ai-agents-env")

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        _build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == expected_variant
        assert kwargs["timeout"] == float(config.execution_timeout)


def test_build_sandbox_colab_forwards_runtime_connection():
    """Colab engine forwards runtime URL, kernel id and proxy token."""
    config = JupyterMCPConfig(
        execution_engine="colab",
        runtime_url="https://colab-host.example",
        runtime_id="kernel-id",
        runtime_proxy_token="proxy-token",
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        _build_sandbox(config, MagicMock())

        mock_create.assert_called_once_with(
            variant="colab",
            timeout=float(config.execution_timeout),
            server_url="https://colab-host.example",
            kernel_id="kernel-id",
            proxy_token="proxy-token",
        )


def test_build_sandbox_datalayer_forwards_token_and_run_url():
    """Datalayer engine forwards runtime auth/settings to code-sandboxes."""
    config = JupyterMCPConfig(
        execution_engine="datalayer",
        runtime_url="https://run.example",
        runtime_token="api-token",
        sandbox_environment="ai-agents-env",
    )

    with patch("code_sandboxes.Sandbox.create") as mock_create:
        mock_create.return_value = MagicMock()

        _build_sandbox(config, MagicMock())

        kwargs = mock_create.call_args.kwargs
        assert kwargs["variant"] == "datalayer"
        assert kwargs["token"] == "api-token"
        assert kwargs["run_url"] == "https://run.example"
        assert kwargs["environment"] == "ai-agents-env"


def test_create_kernel_uses_sandbox_kernel_for_sandbox_engines():
    """Non-jupyter execution engines must use SandboxKernel wrapper."""
    config = JupyterMCPConfig(execution_engine="datalayer", runtime_url="http://localhost:8888")
    fake_sandbox = MagicMock()
    fake_kernel = MagicMock()

    with patch("jupyter_mcp_server.utils._build_sandbox", return_value=fake_sandbox), patch(
        "jupyter_mcp_server.sandbox_kernel.SandboxKernel", return_value=fake_kernel
    ):
        kernel = create_kernel(config, MagicMock())

    assert kernel is fake_kernel
    fake_kernel.start.assert_called_once_with()
