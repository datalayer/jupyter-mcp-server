# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for the Click-based CLI implementation."""

from unittest.mock import patch

import click
import pytest

from jupyter_mcp_server.CLI import connect_command, do_start, stop_command


class _Response:
    def raise_for_status(self):
        return None


def test_click_connect_command_sends_mcp_token():
    """The Click CLI connect command forwards MCP auth to management routes."""
    seen = {}

    def fake_put(url, headers=None, content=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["content"] = content
        return _Response()

    with patch("jupyter_mcp_server.CLI.httpx.put", fake_put):
        connect_command.callback(
            jupyter_mcp_server_url="http://localhost:4040",
            runtime_url=None,
            runtime_id="kernel-id",
            runtime_token=None,
            mcp_token="client-token",
            insecure_mcp_noauth=False,
            document_url=None,
            document_id="notebook.ipynb",
            document_token=None,
            provider="jupyter",
            jupyterlab=True,
            open_notebook_in_ui=False,
            jupyter_url="http://localhost:8888",
            jupyter_token="jupyter-token",
            allowed_jupyter_mcp_tools="notebook_run-all-cells,notebook_get-selected-cell",
            reconnect_interval=0,
            execution_timeout=120,
            max_execution_timeout=3600,
        )
    assert seen["headers"]["Authorization"] == "Bearer client-token"


def test_click_stop_command_sends_mcp_token():
    """The Click CLI stop command forwards MCP auth to management routes."""
    seen = {}

    def fake_delete(url, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Response()

    with patch("jupyter_mcp_server.CLI.httpx.delete", fake_delete):
        stop_command.callback(
            jupyter_mcp_server_url="http://localhost:4040",
            mcp_token="client-token",
        )

    assert seen["headers"]["Authorization"] == "Bearer client-token"


def test_click_start_streamable_http_requires_auth_token():
    """streamable-http cannot start without MCP auth unless explicitly no-auth."""
    with pytest.raises(click.UsageError, match="requires MCP client authentication"):
        do_start(
            transport="streamable-http",
            start_new_runtime=True,
            runtime_url="http://localhost:8888",
            runtime_id=None,
            runtime_token=None,
            document_url="http://localhost:8888",
            document_id=None,
            document_token=None,
            port=4040,
            provider="jupyter",
            jupyterlab=True,
            open_notebook_in_ui=False,
            allowed_jupyter_mcp_tools="notebook_run-all-cells,notebook_get-selected-cell",
            otel_file="",
            mcp_token=None,
            insecure_mcp_noauth=False,
            reconnect_interval=0,
            execution_timeout=120,
            max_execution_timeout=3600,
        )
