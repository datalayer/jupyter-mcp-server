# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Jupyter MCP Server CLI Layer
"""

import click
import httpx
import uvicorn

from jupyter_mcp_server.log import logger
from jupyter_mcp_server.models import DocumentRuntime
from jupyter_mcp_server.config import get_config, set_config
from jupyter_mcp_server.server_context import ServerContext

# Import the server instance and helper functions from server layer
from jupyter_mcp_server.server import (
    mcp,
    __start_kernel,
    __auto_enroll_document,
)

# Shared options decorator to reduce code duplication
def _common_options(f):
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
        )
    ]
    # Apply decorators in reverse order
    for option in reversed(options):
        f = option(f)
    return f


def _resolve_url_and_token_variables(
    jupyter_url, jupyter_token,
    document_url, document_token,
    runtime_url, runtime_token,
) -> tuple[str, str | None, str, str | None]:
    """Resolve URL and token variables based on priority logic.

    Priority order:
    1. Individual URL/token variables take precedence if set
    2. JUPYTER_URL/JUPYTER_TOKEN used as fallback if individual variables are None
    3. Keep original default values if neither individual nor merged variables are set

    Args:
        jupyter_url: The merged Jupyter URL variable
        jupyter_token: The merged Jupyter token variable
        document_url: The individual document URL (takes precedence if set)
        document_token: The individual document token (takes precedence if set)
        runtime_url: The individual runtime URL (takes precedence if set)
        runtime_token: The individual runtime token (takes precedence if set)

    Returns:
        Tuple of (resolved_document_url, resolved_document_token, resolved_runtime_url, resolved_runtime_token)
    """

    # Resolve document_url
    if document_url is not None:
        resolved_document_url = document_url
    elif jupyter_url is not None:
        resolved_document_url = jupyter_url
    else:
        resolved_document_url = "http://localhost:8888"

    # Resolve runtime_url
    if runtime_url is not None:
        resolved_runtime_url = runtime_url
    elif jupyter_url is not None:
        resolved_runtime_url = jupyter_url
    else:
        resolved_runtime_url = "http://localhost:8888"

    # Resolve document_token
    resolved_document_token = document_token or jupyter_token

    # Resolve runtime_token
    resolved_runtime_token = runtime_token or jupyter_token

    return resolved_document_url, resolved_document_token, resolved_runtime_url, resolved_runtime_token


def _do_start(
    transport: str,
    start_new_runtime: bool,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    document_url: str,
    document_id: str,
    document_token: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    allowed_jupyter_mcp_tools: str,
):
    """Internal function to execute the start logic."""

    # Log the received configuration for diagnostics
    # Note: set_config() will automatically normalize string "None" values
    logger.info(
        f"Start command received - runtime_url: {repr(runtime_url)}, "
        f"document_url: {repr(document_url)}, provider: {provider}, "
        f"transport: {transport}"
    )

    # Set configuration using the singleton
    # String "None" values will be automatically normalized by set_config()
    config = set_config(
        transport=transport,
        provider=provider,
        runtime_url=runtime_url,
        start_new_runtime=start_new_runtime,
        runtime_id=runtime_id,
        runtime_token=runtime_token,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        port=port,
        jupyterlab=jupyterlab,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools
    )

    # Reset ServerContext to pick up new configuration
    ServerContext.reset()
    
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

    # Determine startup behavior based on configuration
    if config.document_id:
        # If document_id is provided, auto-enroll the notebook
        # Kernel creation depends on start_new_runtime and runtime_id flags
        try:
            import asyncio
            # Run the async enrollment in the event loop
            asyncio.run(__auto_enroll_document())
        except Exception as e:
            logger.error(f"Failed to auto-enroll document '{config.document_id}': {e}")
            # Fallback to legacy kernel-only mode if enrollment fails
            if config.start_new_runtime or config.runtime_id:
                try:
                    __start_kernel()
                except Exception as e2:
                    logger.error(f"Failed to start kernel on startup: {e2}")
    elif config.start_new_runtime or config.runtime_id:
        # If no document_id but start_new_runtime/runtime_id is set, just create kernel
        # This is for backward compatibility - kernel without managed notebook
        try:
            __start_kernel()
        except Exception as e:
            logger.error(f"Failed to start kernel on startup: {e}")
    # else: No startup action - user must manually enroll notebooks or create kernels

    logger.info(f"Starting Jupyter MCP Server with transport: {transport}")

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=port)  # noqa: S104
    else:
        raise Exception("Transport should be `stdio` or `streamable-http`.")


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
@click.pass_context
def server(
    ctx,
    transport: str,
    start_new_runtime: bool,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    document_url: str,
    document_id: str,
    document_token: str,
    jupyter_url: str,
    jupyter_token: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    allowed_jupyter_mcp_tools: str,
):
    """Manages Jupyter MCP Server.

    When invoked without subcommands, starts the MCP server directly.
    This allows for quick startup with: uvx jupyter-mcp-server

    Subcommands (start, connect, stop) are still available for advanced use cases.
    """
    # If a subcommand is invoked, let it handle the execution
    if ctx.invoked_subcommand is not None:
        return

    # No subcommand provided - execute the default start behavior
    # Resolve URL and token variables based on priority logic
    resolved_document_url, resolved_document_token, resolved_runtime_url, resolved_runtime_token = _resolve_url_and_token_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
    )

    _do_start(
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
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
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
    document_url: str,
    document_id: str,
    document_token: str,
    provider: str,
    jupyterlab: bool,
):
    """Command to connect a Jupyter MCP Server to a document and a runtime."""

    # Set configuration using the singleton
    config = set_config(
        provider=provider,
        runtime_url=runtime_url,
        runtime_id=runtime_id,
        runtime_token=runtime_token,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        jupyterlab=jupyterlab
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
def stop_command(jupyter_mcp_server_url: str):
    r = httpx.delete(
        f"{jupyter_mcp_server_url}/api/stop",
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
def start_command(
    transport: str,
    start_new_runtime: bool,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    document_url: str,
    document_id: str,
    document_token: str,
    jupyter_url: str,
    jupyter_token: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    allowed_jupyter_mcp_tools: str,
):
    """Start the Jupyter MCP server with a transport."""
    # Resolve URL and token variables based on priority logic
    resolved_document_url, resolved_document_token, resolved_runtime_url, resolved_runtime_token = _resolve_url_and_token_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
    )

    _do_start(
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
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
    )


if __name__ == "__main__":
    """Start the Jupyter MCP Server."""
    server()
