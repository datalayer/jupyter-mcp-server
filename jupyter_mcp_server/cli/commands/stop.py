# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Stop command handler for the Typer CLI."""

from typing import Annotated

import httpx
import typer

from jupyter_mcp_server.CLI import _mcp_auth_headers


def stop_command(
    jupyter_mcp_server_url: Annotated[
        str,
        typer.Option(
            "--jupyter-mcp-server-url",
            envvar="JUPYTER_MCP_SERVER_URL",
            help="The URL of the Jupyter MCP Server to stop. Defaults to 'http://localhost:4040'.",
        ),
    ] = "http://localhost:4040",
    mcp_token: Annotated[
        str | None,
        typer.Option("--mcp-token", envvar="MCP_TOKEN"),
    ] = None,
) -> None:
    """Stop the Jupyter MCP Server."""
    response = httpx.delete(
        f"{jupyter_mcp_server_url}/api/stop",
        headers=_mcp_auth_headers(mcp_token),
    )
    response.raise_for_status()
