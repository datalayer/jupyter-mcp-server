#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Simple test script to verify the configuration system works correctly.
"""

from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from jupyter_mcp_server.CLI import _common_options
from jupyter_mcp_server.config import JupyterMCPConfig, get_config, reset_config, set_config


def test_mcp_auth_headers_include_bearer_token():
    """Management CLI requests include the MCP bearer token when configured."""
    from jupyter_mcp_server.CLI import mcp_auth_headers

    assert mcp_auth_headers("client-token") == {
        "Authorization": "Bearer client-token",
    }


def test_mcp_auth_headers_empty_without_token():
    """Management CLI requests stay unauthenticated in explicit no-auth mode."""
    from jupyter_mcp_server.CLI import mcp_auth_headers

    assert mcp_auth_headers(None) == {}


def test_connect_command_sends_mcp_token():
    """The first-party connect command remains compatible with protected routes."""
    from click.testing import CliRunner

    from jupyter_mcp_server.CLI import server

    class Response:
        def raise_for_status(self):
            pass

    seen = {}

    def fake_put(url, headers=None, content=None):
        seen["headers"] = headers
        return Response()

    with patch("jupyter_mcp_server.CLI.httpx.put", fake_put):
        result = CliRunner().invoke(
            server,
            [
                "connect",
                "--jupyter-url",
                "http://localhost:8888",
                "--jupyter-token",
                "jupyter-token",
                "--runtime-id",
                "kernel-id",
                "--document-id",
                "notebook.ipynb",
                "--mcp-token",
                "client-token",
            ],
        )

    assert result.exit_code == 0
    assert seen["headers"]["Authorization"] == "Bearer client-token"


def test_stop_command_sends_mcp_token():
    """The first-party stop command remains compatible with protected routes."""
    from click.testing import CliRunner

    from jupyter_mcp_server.CLI import server

    class Response:
        def raise_for_status(self):
            pass

    seen = {}

    def fake_delete(url, headers=None):
        seen["headers"] = headers
        return Response()

    with patch("jupyter_mcp_server.CLI.httpx.delete", fake_delete):
        result = CliRunner().invoke(server, ["stop", "--mcp-token", "client-token"])

    assert result.exit_code == 0
    assert seen["headers"]["Authorization"] == "Bearer client-token"


def test_config():
    """Test the configuration singleton."""
    print("Testing Jupyter MCP Configuration System")
    print("=" * 50)
    
    # Test default configuration
    config = get_config()
    print(f"Default runtime_url: {config.runtime_url}")
    print(f"Default document_id: {config.document_id}")
    print(f"Default provider: {config.provider}")
    
    # Test setting configuration
    new_config = set_config(
        runtime_url="http://localhost:9999",
        document_id="test_notebooks.ipynb",
        provider="datalayer",
        runtime_token="test_token"
    )
    
    print(f"\nUpdated runtime_url: {new_config.runtime_url}")
    print(f"Updated document_id: {new_config.document_id}")
    print(f"Updated provider: {new_config.provider}")
    print(f"Updated runtime_token: {'***' if new_config.runtime_token else 'None'}")
    
    # Test that singleton works - getting config again should return same values
    config2 = get_config()
    print(f"\nSingleton test - runtime_url: {config2.runtime_url}")
    print(f"Singleton test - document_id: {config2.document_id}")
    
    # Test reset
    reset_config()
    config3 = get_config()
    print(f"\nAfter reset - runtime_url: {config3.runtime_url}")
    print(f"After reset - document_id: {config3.document_id}")
    print(f"After reset - provider: {config3.provider}")
    
    print("\n✅ Configuration system test completed successfully!")


def test_allowed_jupyter_mcp_tools_config():
    """Test the allowed_jupyter_mcp_tools configuration."""
    reset_config()
    
    # Test default configuration
    config = get_config()
    default_tools = config.get_allowed_jupyter_mcp_tools()
    assert "notebook_run-all-cells" in default_tools
    assert "notebook_get-selected-cell" in default_tools
    print(f"Default allowed tools: {default_tools}")
    
    # Test setting custom tools via set_config
    new_config = set_config(allowed_jupyter_mcp_tools="custom_tool1,custom_tool2")
    custom_tools = new_config.get_allowed_jupyter_mcp_tools()
    assert custom_tools == ["custom_tool1", "custom_tool2"]
    print(f"Custom tools: {custom_tools}")
    
    # Test configuration via set_config (simulates how CLI sets the value)
    set_config_result = set_config(allowed_jupyter_mcp_tools="env_tool1,env_tool2")
    env_tools = set_config_result.get_allowed_jupyter_mcp_tools()
    assert env_tools == ["env_tool1", "env_tool2"]
    print(f"CLI-style configuration: {env_tools}")
    
    # Reset to clean state
    reset_config()
    
    # Test comma-separated parsing with spaces
    config_with_spaces = set_config(allowed_jupyter_mcp_tools=" tool1 , tool2 , tool3 ")
    tools_with_spaces = config_with_spaces.get_allowed_jupyter_mcp_tools()
    assert tools_with_spaces == ["tool1", "tool2", "tool3"]
    print(f"Tools with spaces parsed: {tools_with_spaces}")
    
    # Test empty entries filtering
    config_empty = set_config(allowed_jupyter_mcp_tools="tool1,,tool2,")
    tools_filtered = config_empty.get_allowed_jupyter_mcp_tools()
    assert tools_filtered == ["tool1", "tool2"]
    print(f"Empty entries filtered: {tools_filtered}")
    
    print("✅ Allowed jupyter mcp tools configuration test completed successfully!")


def test_jupyter_extension_trait():
    """Test the Jupyter Server Extension trait configuration."""
    from jupyter_mcp_server.jupyter_extension.extension import JupyterMCPServerExtensionApp
    
    # Test default configuration
    app = JupyterMCPServerExtensionApp()
    assert hasattr(app, 'allowed_jupyter_mcp_tools')
    assert app.allowed_jupyter_mcp_tools == "notebook_run-all-cells,notebook_get-selected-cell"
    print(f"Extension default tools: {app.allowed_jupyter_mcp_tools}")
    
    # Test custom configuration
    app.allowed_jupyter_mcp_tools = "custom_ext_tool1,custom_ext_tool2"
    assert app.allowed_jupyter_mcp_tools == "custom_ext_tool1,custom_ext_tool2"
    print(f"Extension custom tools: {app.allowed_jupyter_mcp_tools}")
    
    print("✅ Jupyter extension trait test completed successfully!")


def test_create_kernel_passes_reconnect_interval():
    """Verify create_kernel passes reconnect_interval to KernelClient via client_kwargs."""
    from jupyter_mcp_server.utils import create_kernel

    config = JupyterMCPConfig(
        runtime_url="http://localhost:8888",
        runtime_token="test_token",
        runtime_id="test-kernel-id",
        reconnect_interval=5,
    )

    with patch("jupyter_kernel_client.KernelClient") as MockKernelClient:
        mock_kernel = MagicMock()
        MockKernelClient.return_value = mock_kernel

        create_kernel(config, MagicMock())

        MockKernelClient.assert_called_once_with(
            server_url="http://localhost:8888",
            token="test_token",
            kernel_id="test-kernel-id",
            client_kwargs={"reconnect_interval": 5},
        )
        mock_kernel.start.assert_called_once()

    print("test create_kernel passes reconnect_interval: OK")


def test_create_kernel_no_reconnect_by_default():
    """Verify create_kernel does not pass client_kwargs when reconnect_interval=0."""
    from jupyter_mcp_server.utils import create_kernel

    config = JupyterMCPConfig(
        runtime_url="http://localhost:8888",
        runtime_token="test_token",
        runtime_id="test-kernel-id",
        reconnect_interval=0,
    )

    with patch("jupyter_kernel_client.KernelClient") as MockKernelClient:
        mock_kernel = MagicMock()
        MockKernelClient.return_value = mock_kernel

        create_kernel(config, MagicMock())

        MockKernelClient.assert_called_once_with(
            server_url="http://localhost:8888",
            token="test_token",
            kernel_id="test-kernel-id",
            client_kwargs=None,
        )

    print("test create_kernel no reconnect by default: OK")


def test_reconnect_interval_config():
    """Test the reconnect_interval configuration field."""
    reset_config()

    # Default should be 0 (disabled)
    config = get_config()
    assert config.reconnect_interval == 0

    # Setting a positive value
    new_config = set_config(reconnect_interval=5)
    assert new_config.reconnect_interval == 5

    # Singleton reflects the update
    assert get_config().reconnect_interval == 5

    # Reset restores to 0
    reset_config()
    assert get_config().reconnect_interval == 0

    print("✅ reconnect_interval configuration test completed successfully!")


def test_execution_timeout_env_var_is_read():
    """The documented JUPYTER_MCP_EXECUTION_TIMEOUT env var reaches the CLI option."""
    seen = {}

    @click.command()
    @_common_options
    def _probe(**kwargs):
        seen.update(kwargs)

    result = CliRunner().invoke(
        _probe, [], env={"JUPYTER_MCP_EXECUTION_TIMEOUT": "300"}
    )

    assert result.exit_code == 0, result.output
    assert seen["execution_timeout"] == 300


def test_max_execution_timeout_env_var_is_read():
    """JUPYTER_MCP_MAX_EXECUTION_TIMEOUT reaches the CLI option."""
    seen = {}

    @click.command()
    @_common_options
    def _probe(**kwargs):
        seen.update(kwargs)

    result = CliRunner().invoke(
        _probe, [], env={"JUPYTER_MCP_MAX_EXECUTION_TIMEOUT": "7200"}
    )

    assert result.exit_code == 0, result.output
    assert seen["max_execution_timeout"] == 7200


def test_execution_timeout_defaults_when_env_var_unset():
    """Without the env var, the CLI default matches the config default."""
    seen = {}

    @click.command()
    @_common_options
    def _probe(**kwargs):
        seen.update(kwargs)

    result = CliRunner().invoke(_probe, [], env={})

    assert result.exit_code == 0, result.output
    assert seen["execution_timeout"] == 120
    assert seen["max_execution_timeout"] == 3600


def test_execution_timeout_zero_is_rejected_at_startup():
    """A timeout of 0 fails at startup rather than expiring every execution."""
    ran = []

    @click.command()
    @_common_options
    def _probe(**kwargs):
        ran.append(True)

    result = CliRunner().invoke(
        _probe, [], env={"JUPYTER_MCP_EXECUTION_TIMEOUT": "0"}
    )

    assert result.exit_code != 0
    assert not ran, "startup continued with a timeout that expires immediately"


def test_execution_timeout_config_rejects_non_positive():
    """The config object itself refuses a non-positive execution timeout."""
    reset_config()

    with pytest.raises(ValidationError):
        JupyterMCPConfig(execution_timeout=0)

    with pytest.raises(ValidationError):
        JupyterMCPConfig(max_execution_timeout=0)

    # validate_assignment=True means the singleton rejects it too
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

    # Singleton reflects the update
    assert get_config().execution_timeout == 300

    # Reset restores the default
    reset_config()
    assert get_config().execution_timeout == 120

    print("✅ execution_timeout configuration test completed successfully!")


if __name__ == "__main__":
    test_config()
    test_allowed_jupyter_mcp_tools_config()
    test_jupyter_extension_trait()
    test_reconnect_interval_config()
    test_execution_timeout_config()
