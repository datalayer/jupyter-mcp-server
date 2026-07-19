# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Typer CLI app composed from separated command modules."""

import typer

from jupyter_mcp_server.cli.commands.connect import Provider, connect_command
from jupyter_mcp_server.cli.commands.serve import server_callback, start_command
from jupyter_mcp_server.cli.commands.stop import stop_command

app = typer.Typer(
    name="jupyter-mcp-server-typer",
    add_completion=False,
    no_args_is_help=False,
)

app.callback(invoke_without_command=True)(server_callback)
app.command("start")(start_command)
app.command("connect")(connect_command)
app.command("stop")(stop_command)


def serve() -> None:
    """Console-script entrypoint for the Typer CLI."""
    app()

__all__ = [
    "Provider",
    "app",
    "connect_command",
    "start_command",
    "stop_command",
    "serve",
]


if __name__ == "__main__":
    serve()
