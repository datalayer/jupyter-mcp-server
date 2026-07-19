# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Regression tests for the Typer-based CLI implementation."""

from unittest.mock import patch

from typer.testing import CliRunner

from jupyter_mcp_server.cli.cli import Provider, app, connect_command, stop_command


class _Response:
    def raise_for_status(self):
        return None


def test_typer_connect_command_sends_mcp_token():
    """The Typer CLI connect command forwards MCP auth to management routes."""
    seen = {}

    def fake_put(url, headers=None, content=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["content"] = content
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


def test_typer_stop_command_sends_mcp_token():
    """The Typer CLI stop command forwards MCP auth to management routes."""
    seen = {}

    def fake_delete(url, headers=None):
        seen["url"] = url
        seen["headers"] = headers
        return _Response()

    with patch("jupyter_mcp_server.cli.commands.stop.httpx.delete", fake_delete):
        stop_command(
            jupyter_mcp_server_url="http://localhost:4040",
            mcp_token="client-token",
        )

    assert seen["headers"]["Authorization"] == "Bearer client-token"


def test_typer_start_streamable_http_requires_auth_token():
    """Typer start keeps the same streamable-http auth guard as Click."""
    result = CliRunner().invoke(
        app,
        [
            "start",
            "--transport",
            "streamable-http",
        ],
    )

    assert result.exit_code != 0
    assert "requires MCP client authentication" in result.output


def test_typer_root_accepts_explicit_start_new_runtime_bool_value():
    """Module-style invocation accepts '--start-new-runtime False' legacy form."""
    seen = {}

    def fake_do_start(**kwargs):
        seen.update(kwargs)

    with patch("jupyter_mcp_server.cli.commands.serve.do_start", fake_do_start):
        result = CliRunner().invoke(
            app,
            [
                "--transport",
                "stdio",
                "--start-new-runtime",
                "False",
            ],
        )

    assert result.exit_code == 0, result.output
    assert seen["start_new_runtime"] is False
