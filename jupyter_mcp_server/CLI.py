# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Jupyter MCP Server CLI Layer
"""

from typing import NamedTuple, Optional

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
def _connection_options(f):
    """Decorator adding options that identify the document and runtime servers.

    These are the only options needed by `connect` (which forwards them to a
    remote MCP server). `_common_options` extends this with start-time-only
    options like MCP auth and `--jupyter-*` aliases.
    """
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
            "--runtime-password",
            envvar="RUNTIME_PASSWORD",
            type=click.STRING,
            default=None,
            help="Password for runtime Jupyter server authentication. Takes precedence over --runtime-token if both are set.",
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
            "--document-password",
            envvar="DOCUMENT_PASSWORD",
            type=click.STRING,
            default=None,
            help="Password for document Jupyter server authentication. Takes precedence over --document-token if both are set.",
        ),
    ]
    for option in reversed(options):
        f = option(f)
    return f


def _common_options(f):
    """Decorator adding all start-time options (extends `_connection_options`)."""
    f = _connection_options(f)
    extra_options = [
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
            "--jupyter-password",
            envvar="JUPYTER_PASSWORD",
            type=click.STRING,
            default=None,
            help="Shared password for both runtime and document servers (fallback if individual passwords not set). Takes precedence over --jupyter-token if both are set.",
        ),
        click.option(
            "--allowed-jupyter-mcp-tools",
            envvar="ALLOWED_JUPYTER_MCP_TOOLS",
            type=click.STRING,
            default="notebook_run-all-cells,notebook_get-selected-cell",
            help="Comma-separated list of jupyter-mcp-tools to enable. Defaults to 'notebook_run-all-cells,notebook_get-selected-cell' - Only applicable when run as jupyter server extension.",
        ),
    ]
    for option in reversed(extra_options):
        f = option(f)
    return f


class _ResolvedConnection(NamedTuple):
    """Result of resolving connection variables (URL, token, password) for both servers."""
    document_url: str
    document_token: Optional[str]
    runtime_url: str
    runtime_token: Optional[str]
    document_password: Optional[str]
    runtime_password: Optional[str]


def _resolve_connection_variables(
    *,
    jupyter_url: Optional[str],
    jupyter_token: Optional[str],
    document_url: Optional[str],
    document_token: Optional[str],
    runtime_url: Optional[str],
    runtime_token: Optional[str],
    jupyter_password: Optional[str] = None,
    document_password: Optional[str] = None,
    runtime_password: Optional[str] = None,
) -> _ResolvedConnection:
    """Resolve URL, token, and password variables based on priority logic.

    Priority order:
    1. Individual variables (document_*, runtime_*) take precedence if set
    2. Shared `jupyter_*` variables used as fallback if individual variables are None
    3. Default values when neither individual nor shared variables are set
    """
    default_url = "http://localhost:8888"
    return _ResolvedConnection(
        document_url=document_url or jupyter_url or default_url,
        document_token=document_token or jupyter_token,
        runtime_url=runtime_url or jupyter_url or default_url,
        runtime_token=runtime_token or jupyter_token,
        document_password=document_password or jupyter_password,
        runtime_password=runtime_password or jupyter_password,
    )


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
    otel_file: str = "",
    mcp_token: str = None,
    insecure_mcp_noauth: bool = False,
    runtime_password: str = None,
    document_password: str = None,
):
    """Internal function to execute the start logic."""

    # Validate MCP auth configuration early, before any heavy startup work
    if transport == "streamable-http" and not mcp_token and not insecure_mcp_noauth:
        raise click.UsageError(
            "streamable-http transport requires MCP client authentication. "
            "Set --mcp-token / MCP_TOKEN, or pass --insecure-mcp-noauth to "
            "explicitly allow unauthenticated access."
        )

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
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        runtime_password=runtime_password,
        document_password=document_password,
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

    # Auto-register OTel hook handler if configured (CLI arg → env var fallback)
    from jupyter_mcp_server.otel_hook import maybe_register_otel
    maybe_register_otel(otel_file or None)

    # Configure token authentication for the MCP endpoint
    if transport == "streamable-http":
        if mcp_token:
            from jupyter_mcp_server.server import RuntimeTokenVerifier
            mcp._token_verifier = RuntimeTokenVerifier(mcp_token)
            logger.info("MCP endpoint token authentication enabled (using MCP_TOKEN)")
        elif insecure_mcp_noauth:
            logger.warning(
                "MCP endpoint authentication DISABLED (--insecure-mcp-noauth). "
                "Any client can connect without credentials. Not recommended for production."
            )
        else:
            # Unreachable: early validation in start_command / server should have caught
            # this. Use raise (not assert) so `python -O` doesn't strip the check.
            raise RuntimeError("MCP auth config missing; early validation should have caught this")

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
    runtime_password: str,
    document_password: str,
    jupyter_password: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    allowed_jupyter_mcp_tools: str,
    otel_file: str,
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
    # Resolve URL, token, and password variables based on priority logic
    resolved = _resolve_connection_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
        jupyter_password=jupyter_password,
        document_password=document_password,
        runtime_password=runtime_password,
    )

    _do_start(
        transport=transport,
        start_new_runtime=start_new_runtime,
        runtime_url=resolved.runtime_url,
        runtime_id=runtime_id,
        runtime_token=resolved.runtime_token,
        document_url=resolved.document_url,
        document_id=document_id,
        document_token=resolved.document_token,
        port=port,
        provider=provider,
        jupyterlab=jupyterlab,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        runtime_password=resolved.runtime_password,
        document_password=resolved.document_password,
    )


@server.command("connect")
@_connection_options
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
    runtime_password: str,
    document_url: str,
    document_id: str,
    document_token: str,
    document_password: str,
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
        runtime_password=runtime_password,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        document_password=document_password,
        jupyterlab=jupyterlab,
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
    runtime_password: str,
    document_password: str,
    jupyter_password: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    allowed_jupyter_mcp_tools: str,
    otel_file: str,
):
    """Start the Jupyter MCP server with a transport."""
    # Resolve URL, token, and password variables based on priority logic
    resolved = _resolve_connection_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
        jupyter_password=jupyter_password,
        document_password=document_password,
        runtime_password=runtime_password,
    )

    _do_start(
        transport=transport,
        start_new_runtime=start_new_runtime,
        runtime_url=resolved.runtime_url,
        runtime_id=runtime_id,
        runtime_token=resolved.runtime_token,
        document_url=resolved.document_url,
        document_id=document_id,
        document_token=resolved.document_token,
        port=port,
        provider=provider,
        jupyterlab=jupyterlab,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        runtime_password=resolved.runtime_password,
        document_password=resolved.document_password,
    )


if __name__ == "__main__":
    """Start the Jupyter MCP Server."""
    server()
