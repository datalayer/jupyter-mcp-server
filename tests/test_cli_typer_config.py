#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Typer-based config and option tests mirroring the Click config test suite."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from jupyter_mcp_server.cli.cli import Provider, app, connect_command, stop_command
from jupyter_mcp_server.config import JupyterMCPConfig, get_config, reset_config, set_config
from jupyter_mcp_server.utils import mcp_auth_headers


class _Response:
    def raise_for_status(self):
        return None


def test_mcp_auth_headers_include_bearer_token():
    """Management CLI requests include the MCP bearer token when configured."""
    assert mcp_auth_headers("client-token") == {
        "Authorization": "Bearer client-token",
    }


def test_mcp_auth_headers_empty_without_token():
    """Management CLI requests stay unauthenticated in explicit no-auth mode."""
    assert mcp_auth_headers(None) == {}


def test_connect_command_sends_mcp_token():
    """The Typer connect command remains compatible with protected routes."""
    reset_config()
    seen = {}

    def fake_put(url, headers=None, content=None):
        seen["headers"] = headers
        return _Response()

    with patch("jupyter_mcp_server.cli.commands.connect.httpx.put", fake_put):
        connect_command(
            jupyter_mcp_server_url="http://localhost:4040",
            provider=Provider.jupyter,
            jupyterlab=True,
            open_notebook_in_ui=False,
            runtime_url=None,
            runtime_id="kernel-id",
            runtime_token=None,
            mcp_token="client-token",
            document_url=None,
            document_id="notebook.ipynb",
            document_token=None,
            jupyter_url="http://localhost:8888",
            jupyter_token="jupyter-token",
        )

    assert seen["headers"]["Authorization"] == "Bearer client-token"


def test_stop_command_sends_mcp_token():
    """The Typer stop command remains compatible with protected routes."""
    seen = {}

    def fake_delete(url, headers=None):
        seen["headers"] = headers
        return _Response()

    with patch("jupyter_mcp_server.cli.commands.stop.httpx.delete", fake_delete):
        stop_command(
            jupyter_mcp_server_url="http://localhost:4040",
            mcp_token="client-token",
        )

    assert seen["headers"]["Authorization"] == "Bearer client-token"


def test_config():
    """Test the configuration singleton."""
    reset_config()

    config = get_config()
    assert config.runtime_url == "http://localhost:8888"
    assert config.document_id is None
    assert config.provider == "jupyter"

    new_config = set_config(
        runtime_url="http://localhost:9999",
        document_id="test_notebooks.ipynb",
        provider="datalayer",
        runtime_token="test_token",
    )

    assert new_config.runtime_url == "http://localhost:9999"
    assert new_config.document_id == "test_notebooks.ipynb"
    assert new_config.provider == "datalayer"

    config2 = get_config()
    assert config2.runtime_url == "http://localhost:9999"
    assert config2.document_id == "test_notebooks.ipynb"

    reset_config()
    config3 = get_config()
    assert config3.runtime_url == "http://localhost:8888"
    assert config3.document_id is None
    assert config3.provider == "jupyter"


def test_allowed_jupyter_mcp_tools_config():
    """Test the allowed_jupyter_mcp_tools configuration."""
    reset_config()

    config = get_config()
    default_tools = config.get_allowed_jupyter_mcp_tools()
    assert "notebook_run-all-cells" in default_tools
    assert "notebook_get-selected-cell" in default_tools

    new_config = set_config(allowed_jupyter_mcp_tools="custom_tool1,custom_tool2")
    custom_tools = new_config.get_allowed_jupyter_mcp_tools()
    assert custom_tools == ["custom_tool1", "custom_tool2"]

    set_config_result = set_config(allowed_jupyter_mcp_tools="env_tool1,env_tool2")
    env_tools = set_config_result.get_allowed_jupyter_mcp_tools()
    assert env_tools == ["env_tool1", "env_tool2"]

    reset_config()

    config_with_spaces = set_config(allowed_jupyter_mcp_tools=" tool1 , tool2 , tool3 ")
    tools_with_spaces = config_with_spaces.get_allowed_jupyter_mcp_tools()
    assert tools_with_spaces == ["tool1", "tool2", "tool3"]

    config_empty = set_config(allowed_jupyter_mcp_tools="tool1,,tool2,")
    tools_filtered = config_empty.get_allowed_jupyter_mcp_tools()
    assert tools_filtered == ["tool1", "tool2"]


def test_jupyter_extension_trait():
    """Test the Jupyter Server Extension trait configuration."""
    from jupyter_mcp_server.jupyter_extension.extension import JupyterMCPServerExtensionApp

    extension_app = JupyterMCPServerExtensionApp()
    assert hasattr(extension_app, "allowed_jupyter_mcp_tools")
    assert (
        extension_app.allowed_jupyter_mcp_tools
        == "notebook_run-all-cells,notebook_get-selected-cell"
    )

    extension_app.allowed_jupyter_mcp_tools = "custom_ext_tool1,custom_ext_tool2"
    assert extension_app.allowed_jupyter_mcp_tools == "custom_ext_tool1,custom_ext_tool2"


def test_create_kernel_passes_reconnect_interval():
    """Verify create_kernel passes reconnect_interval to KernelClient via client_kwargs."""
    from jupyter_mcp_server.utils import create_kernel

    config = JupyterMCPConfig(
        runtime_url="http://localhost:8888",
        runtime_token="test_token",
        runtime_id="test-kernel-id",
        reconnect_interval=5,
    )

    with patch("jupyter_kernel_client.KernelClient") as mock_kernel_client:
        mock_kernel = MagicMock()
        mock_kernel_client.return_value = mock_kernel

        create_kernel(config, MagicMock())

        mock_kernel_client.assert_called_once_with(
            server_url="http://localhost:8888",
            token="test_token",
            kernel_id="test-kernel-id",
            client_kwargs={"reconnect_interval": 5},
        )
        mock_kernel.start.assert_called_once()


def test_create_kernel_no_reconnect_by_default():
    """Verify create_kernel does not pass client_kwargs when reconnect_interval=0."""
    from jupyter_mcp_server.utils import create_kernel

    config = JupyterMCPConfig(
        runtime_url="http://localhost:8888",
        runtime_token="test_token",
        runtime_id="test-kernel-id",
        reconnect_interval=0,
    )

    with patch("jupyter_kernel_client.KernelClient") as mock_kernel_client:
        mock_kernel = MagicMock()
        mock_kernel_client.return_value = mock_kernel

        create_kernel(config, MagicMock())

        mock_kernel_client.assert_called_once_with(
            server_url="http://localhost:8888",
            token="test_token",
            kernel_id="test-kernel-id",
            client_kwargs=None,
        )


def test_reconnect_interval_config():
    """Test the reconnect_interval configuration field."""
    reset_config()

    config = get_config()
    assert config.reconnect_interval == 0

    new_config = set_config(reconnect_interval=5)
    assert new_config.reconnect_interval == 5

    assert get_config().reconnect_interval == 5

    reset_config()
    assert get_config().reconnect_interval == 0


def test_execution_timeout_env_var_is_read():
    """The documented JUPYTER_MCP_EXECUTION_TIMEOUT env var reaches Typer options."""
    seen = {}

    def fake_do_start(**kwargs):
        seen.update(kwargs)

    with patch("jupyter_mcp_server.cli.commands.serve.do_start", fake_do_start):
        result = CliRunner().invoke(
            app,
            ["start"],
            env={"JUPYTER_MCP_EXECUTION_TIMEOUT": "300"},
        )

    assert result.exit_code == 0, result.output
    assert seen["execution_timeout"] == 300


def test_max_execution_timeout_env_var_is_read():
    """JUPYTER_MCP_MAX_EXECUTION_TIMEOUT reaches Typer options."""
    seen = {}

    def fake_do_start(**kwargs):
        seen.update(kwargs)

    with patch("jupyter_mcp_server.cli.commands.serve.do_start", fake_do_start):
        result = CliRunner().invoke(
            app,
            ["start"],
            env={"JUPYTER_MCP_MAX_EXECUTION_TIMEOUT": "7200"},
        )

    assert result.exit_code == 0, result.output
    assert seen["max_execution_timeout"] == 7200


def test_execution_timeout_defaults_when_env_var_unset():
    """Without env vars, Typer defaults match config defaults."""
    seen = {}

    def fake_do_start(**kwargs):
        seen.update(kwargs)

    with patch("jupyter_mcp_server.cli.commands.serve.do_start", fake_do_start):
        result = CliRunner().invoke(app, ["start"], env={})

    assert result.exit_code == 0, result.output
    assert seen["execution_timeout"] == 120
    assert seen["max_execution_timeout"] == 3600


def test_execution_timeout_zero_is_rejected_at_startup():
    """A timeout of 0 fails at CLI validation before startup executes."""
    ran = []

    def fake_do_start(**kwargs):
        ran.append(kwargs)

    with patch("jupyter_mcp_server.cli.commands.serve.do_start", fake_do_start):
        result = CliRunner().invoke(
            app,
            ["start"],
            env={"JUPYTER_MCP_EXECUTION_TIMEOUT": "0"},
        )

    assert result.exit_code != 0
    assert not ran


def test_execution_timeout_config_rejects_non_positive():
    """The config object itself refuses a non-positive execution timeout."""
    reset_config()

    with pytest.raises(ValidationError):
        JupyterMCPConfig(execution_timeout=0)

    with pytest.raises(ValidationError):
        JupyterMCPConfig(max_execution_timeout=0)

    with pytest.raises(ValidationError):
        set_config(execution_timeout=0)

    reset_config()


def test_execution_timeout_config():
    """Test the execution_timeout configuration field."""
    reset_config()

    config = get_config()
    assert config.execution_timeout == 120
    assert config.max_execution_timeout == 3600

    new_config = set_config(execution_timeout=300)
    assert new_config.execution_timeout == 300

    assert get_config().execution_timeout == 300

    reset_config()
    assert get_config().execution_timeout == 120
