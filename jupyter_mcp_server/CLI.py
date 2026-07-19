# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Deprecated Click-based Jupyter MCP Server CLI layer.

This module is kept for backward compatibility while the project migrates to
the Typer CLI implementation in jupyter_mcp_server.cli.cli.
"""

from collections.abc import Callable
from typing import Any

import click
import httpx

from jupyter_mcp_server.log import logger
from jupyter_mcp_server.models import DocumentRuntime
from jupyter_mcp_server.config import get_config, set_config
from jupyter_mcp_server.utils import (
    do_start,
    mcp_auth_headers,
    resolve_url_and_token_variables,
)

# Shared options decorator to reduce code duplication
def _common_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that adds common start options to a command."""
    options = [
        click.option(
            "--provider",
            envvar="PROVIDER",
            type=click.Choice(["jupyter", "datalayer"]),
            default="jupyter",
            help="The provider to use for the document and runtime. Defaults to 'jupyter'.",
        ),
        click.option(
            "--jupyterlab",
            envvar="JUPYTERLAB",
            type=click.BOOL,
            default=True,
            help="Enable JupyterLab mode. Defaults to True.",
        ),
        click.option(
            "--open-notebook-in-ui",
            envvar="OPEN_NOTEBOOK_IN_UI",
            type=click.BOOL,
            default=False,
            help="Open the notebook in the JupyterLab UI when using it, which activates its tab. Defaults to False.",
        ),
        click.option(
            "--runtime-url",
            envvar="RUNTIME_URL",
            type=click.STRING,
            default=None,
            help="The runtime URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer runtime URL.",
        ),
        click.option(
            "--runtime-id",
            envvar="RUNTIME_ID",
            type=click.STRING,
            default=None,
            help="The kernel ID to use. If not provided, a new kernel should be started.",
        ),
        click.option(
            "--runtime-token",
            envvar="RUNTIME_TOKEN",
            type=click.STRING,
            default=None,
            help="The runtime token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
        ),
        click.option(
            "--mcp-token",
            envvar="MCP_TOKEN",
            type=click.STRING,
            default=None,
            help="Token for authenticating MCP clients (Bearer scheme). Required for streamable-http unless --insecure-mcp-noauth is set.",
        ),
        click.option(
            "--insecure-mcp-noauth",
            envvar="INSECURE_MCP_NOAUTH",
            is_flag=True,
            default=False,
            help="Allow running streamable-http transport without MCP client authentication. NOT recommended for production.",
        ),
        click.option(
            "--document-url",
            envvar="DOCUMENT_URL",
            type=click.STRING,
            default=None,
            help="The document URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer document URL.",
        ),
        click.option(
            "--document-id",
            envvar="DOCUMENT_ID",
            type=click.STRING,
            default=None,
            help="The document id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path. Optional - if omitted, you can list and select notebooks interactively.",
        ),
        click.option(
            "--document-token",
            envvar="DOCUMENT_TOKEN",
            type=click.STRING,
            default=None,
            help="The document token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
        ),
        click.option(
            "--jupyter-url",
            envvar="JUPYTER_URL",
            type=click.STRING,
            default=None,
            help="The Jupyter URL to use as default for both document and runtime URLs. If not provided, individual URL settings take precedence.",
        ),
        click.option(
            "--jupyter-token",
            envvar="JUPYTER_TOKEN",
            type=click.STRING,
            default=None,
            help="The Jupyter token to use as default for both document and runtime tokens. If not provided, individual token settings take precedence.",
        ),
        click.option(
            "--allowed-jupyter-mcp-tools",
            envvar="ALLOWED_JUPYTER_MCP_TOOLS",
            type=click.STRING,
            default="notebook_run-all-cells,notebook_get-selected-cell",
            help="Comma-separated list of jupyter-mcp-tools to enable. Defaults to 'notebook_run-all-cells,notebook_get-selected-cell' - Only applicable when run as jupyter server extension.",
        ),
        click.option(
            "--reconnect-interval",
            envvar="RECONNECT_INTERVAL",
            type=click.INT,
            default=0,
            help="Seconds to wait before reconnecting a dropped WebSocket connection to the kernel. Defaults to 0 (disabled).",
        ),
        click.option(
            "--execution-timeout",
            envvar="JUPYTER_MCP_EXECUTION_TIMEOUT",
            type=click.IntRange(min=1),
            default=120,
            help="Default timeout in seconds for code execution, used when a tool call does not pass its own timeout. Defaults to 120.",
        ),
        click.option(
            "--max-execution-timeout",
            envvar="JUPYTER_MCP_MAX_EXECUTION_TIMEOUT",
            type=click.IntRange(min=1),
            default=3600,
            help="Maximum timeout in seconds a tool call may request for code execution. Defaults to 3600.",
        ),
    ]
    # Apply decorators in reverse order
    for option in reversed(options):
        f = option(f)
    return f


def _log_click_cli_deprecation() -> None:
    """Log a deprecation notice for the legacy Click CLI surface."""
    logger.warning(
        "jupyter_mcp_server.CLI is deprecated and will be removed in a future "
        "release. Please migrate to the Typer CLI (jupyter_mcp_server.cli.cli)."
    )


@click.group(invoke_without_command=True)
@_common_options
@click.option(
    "--transport",
    envvar="TRANSPORT",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="The transport to use for the MCP server. Defaults to 'stdio'.",
)
@click.option(
    "--start-new-runtime",
    envvar="START_NEW_RUNTIME",
    type=click.BOOL,
    default=True,
    help="Start a new runtime or use an existing one.",
)
@click.option(
    "--port",
    envvar="PORT",
    type=click.INT,
    default=4040,
    help="The port to use for the Streamable HTTP transport. Ignored for stdio transport.",
)
@click.option(
    "--otel-file",
    envvar="JUPYTER_MCP_OTEL_FILE",
    type=click.STRING,
    default="",
    help="Path to JSONL file for OpenTelemetry span export.",
)
@click.pass_context
def server(
    ctx,
    transport: str,
    start_new_runtime: bool,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    mcp_token: str,
    insecure_mcp_noauth: bool,
    document_url: str,
    document_id: str,
    document_token: str,
    jupyter_url: str,
    jupyter_token: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    open_notebook_in_ui: bool,
    allowed_jupyter_mcp_tools: str,
    otel_file: str,
    reconnect_interval: int,
    execution_timeout: int,
    max_execution_timeout: int,
):
    """Manages Jupyter MCP Server.

    When invoked without subcommands, starts the MCP server directly.
    This allows for quick startup with: uvx jupyter-mcp-server

    Subcommands (start, connect, stop) are still available for advanced use cases.
    """
    _log_click_cli_deprecation()

    # If a subcommand is invoked, let it handle the execution
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand provided - execute the default start behavior
    # Resolve URL and token variables based on priority logic
    resolved_document_url, resolved_document_token, resolved_runtime_url, resolved_runtime_token = resolve_url_and_token_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
    )

    do_start(
        transport=transport,
        start_new_runtime=start_new_runtime,
        runtime_url=resolved_runtime_url,
        runtime_id=runtime_id,
        runtime_token=resolved_runtime_token,
        document_url=resolved_document_url,
        document_id=document_id,
        document_token=resolved_document_token,
        port=port,
        provider=provider,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
    )


@server.command("connect")
@_common_options
@click.option(
    "--jupyter-mcp-server-url",
    envvar="JUPYTER_MCP_SERVER_URL",
    type=click.STRING,
    default="http://localhost:4040",
    help="The URL of the Jupyter MCP Server to connect to. Defaults to 'http://localhost:4040'.",
)
def connect_command(
    jupyter_mcp_server_url: str,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    mcp_token: str,
    insecure_mcp_noauth: bool,
    document_url: str,
    document_id: str,
    document_token: str,
    provider: str,
    jupyterlab: bool,
    open_notebook_in_ui: bool,
    jupyter_url: str,
    jupyter_token: str,
    allowed_jupyter_mcp_tools: str,
    reconnect_interval: int,
    execution_timeout: int,
    max_execution_timeout: int,
):
    """Command to connect a Jupyter MCP Server to a document and a runtime."""

    resolved_document_url, resolved_document_token, resolved_runtime_url, resolved_runtime_token = resolve_url_and_token_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
    )

    # Set configuration using the singleton
    config = set_config(
        provider=provider,
        runtime_url=resolved_runtime_url,
        runtime_id=runtime_id,
        runtime_token=resolved_runtime_token,
        document_url=resolved_document_url,
        document_id=document_id,
        document_token=resolved_document_token,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui
    )
    
    # Also update the jupyter_extension ServerContext with the jupyterlab flag
    # This is critical for MCP_SERVER mode to propagate the config properly
    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context
        extension_context = get_server_context()
        extension_context.update(
            context_type="MCP_SERVER",
            serverapp=None,
            document_url=config.document_url,
            runtime_url=config.runtime_url,
            jupyterlab=config.jupyterlab
        )
        logger.info(f"Updated jupyter_extension ServerContext with jupyterlab={config.jupyterlab}")
    except Exception as e:
        logger.warning(f"Failed to update jupyter_extension ServerContext: {e}")

    config = get_config()

    document_runtime = DocumentRuntime(
        provider=config.provider,
        runtime_url=config.runtime_url,
        runtime_id=config.runtime_id,
        runtime_token=config.runtime_token,
        document_url=config.document_url,
        document_id=config.document_id,
        document_token=config.document_token,
    )

    r = httpx.put(
        f"{jupyter_mcp_server_url}/api/connect",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **mcp_auth_headers(mcp_token),
        },
        content=document_runtime.model_dump_json(),
    )
    r.raise_for_status()


@server.command("stop")
@click.option(
    "--jupyter-mcp-server-url",
    envvar="JUPYTER_MCP_SERVER_URL",
    type=click.STRING,
    default="http://localhost:4040",
    help="The URL of the Jupyter MCP Server to stop. Defaults to 'http://localhost:4040'.",
)
@click.option(
    "--mcp-token",
    envvar="MCP_TOKEN",
    type=click.STRING,
    default=None,
    help="Token for authenticating to the Jupyter MCP Server management route.",
)
def stop_command(jupyter_mcp_server_url: str, mcp_token: str):
    r = httpx.delete(
        f"{jupyter_mcp_server_url}/api/stop",
        headers=mcp_auth_headers(mcp_token),
    )
    r.raise_for_status()


@server.command("start")
@_common_options
@click.option(
    "--transport",
    envvar="TRANSPORT",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="The transport to use for the MCP server. Defaults to 'stdio'.",
)
@click.option(
    "--start-new-runtime",
    envvar="START_NEW_RUNTIME",
    type=click.BOOL,
    default=True,
    help="Start a new runtime or use an existing one.",
)
@click.option(
    "--port",
    envvar="PORT",
    type=click.INT,
    default=4040,
    help="The port to use for the Streamable HTTP transport. Ignored for stdio transport.",
)
@click.option(
    "--otel-file",
    envvar="JUPYTER_MCP_OTEL_FILE",
    type=click.STRING,
    default="",
    help="Path to JSONL file for OpenTelemetry span export.",
)
def start_command(
    transport: str,
    start_new_runtime: bool,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    mcp_token: str,
    insecure_mcp_noauth: bool,
    document_url: str,
    document_id: str,
    document_token: str,
    jupyter_url: str,
    jupyter_token: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    open_notebook_in_ui: bool,
    allowed_jupyter_mcp_tools: str,
    otel_file: str,
    reconnect_interval: int,
    execution_timeout: int,
    max_execution_timeout: int,
):
    """Start the Jupyter MCP Server with a transport."""
    # Resolve URL and token variables based on priority logic
    resolved_document_url, resolved_document_token, resolved_runtime_url, resolved_runtime_token = resolve_url_and_token_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
    )

    do_start(
        transport=transport,
        start_new_runtime=start_new_runtime,
        runtime_url=resolved_runtime_url,
        runtime_id=runtime_id,
        runtime_token=resolved_runtime_token,
        document_url=resolved_document_url,
        document_id=document_id,
        document_token=resolved_document_token,
        port=port,
        provider=provider,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
    )


if __name__ == "__main__":
    """Start the Jupyter MCP Server."""
    server()
