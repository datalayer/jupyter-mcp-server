"""Serve/start command handlers for the Typer CLI."""

from typing import Annotated

import click
import typer

from jupyter_mcp_server.CLI import _do_start, _resolve_url_and_token_variables


def _resolve_and_start(
    transport: str,
    start_new_runtime: bool,
    runtime_url: str | None,
    runtime_id: str | None,
    runtime_token: str | None,
    mcp_token: str | None,
    insecure_mcp_noauth: bool,
    document_url: str | None,
    document_id: str | None,
    document_token: str | None,
    jupyter_url: str | None,
    jupyter_token: str | None,
    port: int,
    provider: str,
    jupyterlab: bool,
    open_notebook_in_ui: bool,
    allowed_jupyter_mcp_tools: str,
    otel_file: str,
    reconnect_interval: int,
    execution_timeout: int,
    max_execution_timeout: int,
) -> None:
    (
        resolved_document_url,
        resolved_document_token,
        resolved_runtime_url,
        resolved_runtime_token,
    ) = _resolve_url_and_token_variables(
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
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
    )


def server_callback(
    ctx: typer.Context,
    transport: Annotated[
        str,
        typer.Option(
            "--transport",
            envvar="TRANSPORT",
            click_type=click.Choice(["stdio", "streamable-http"]),
            help="The transport to use for the MCP server. Defaults to 'stdio'.",
        ),
    ] = "stdio",
    start_new_runtime: Annotated[
        bool,
        typer.Option(
            "--start-new-runtime",
            envvar="START_NEW_RUNTIME",
            click_type=click.BOOL,
            help="Start a new runtime or use an existing one.",
        ),
    ] = True,
    port: Annotated[
        int,
        typer.Option(
            "--port",
            envvar="PORT",
            help="The port to use for the Streamable HTTP transport. Ignored for stdio transport.",
        ),
    ] = 4040,
    otel_file: Annotated[
        str,
        typer.Option(
            "--otel-file",
            envvar="JUPYTER_MCP_OTEL_FILE",
            help="Path to JSONL file for OpenTelemetry span export.",
        ),
    ] = "",
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            envvar="PROVIDER",
            click_type=click.Choice(["jupyter", "datalayer"]),
            help="The provider to use for the document and runtime. Defaults to 'jupyter'.",
        ),
    ] = "jupyter",
    jupyterlab: Annotated[
        bool,
        typer.Option(
            "--jupyterlab",
            envvar="JUPYTERLAB",
            click_type=click.BOOL,
            help="Enable JupyterLab mode. Defaults to True.",
        ),
    ] = True,
    open_notebook_in_ui: Annotated[
        bool,
        typer.Option(
            "--open-notebook-in-ui",
            envvar="OPEN_NOTEBOOK_IN_UI",
            click_type=click.BOOL,
            help="Open the notebook in the JupyterLab UI when using it, which activates its tab. Defaults to False.",
        ),
    ] = False,
    runtime_url: Annotated[
        str | None,
        typer.Option(
            "--runtime-url",
            envvar="RUNTIME_URL",
            help="The runtime URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer runtime URL.",
        ),
    ] = None,
    runtime_id: Annotated[
        str | None,
        typer.Option(
            "--runtime-id",
            envvar="RUNTIME_ID",
            help="The kernel ID to use. If not provided, a new kernel should be started.",
        ),
    ] = None,
    runtime_token: Annotated[
        str | None,
        typer.Option(
            "--runtime-token",
            envvar="RUNTIME_TOKEN",
            help="The runtime token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
        ),
    ] = None,
    mcp_token: Annotated[
        str | None,
        typer.Option(
            "--mcp-token",
            envvar="MCP_TOKEN",
            help="Token for authenticating MCP clients (Bearer scheme). Required for streamable-http unless --insecure-mcp-noauth is set.",
        ),
    ] = None,
    insecure_mcp_noauth: Annotated[
        bool,
        typer.Option(
            "--insecure-mcp-noauth",
            envvar="INSECURE_MCP_NOAUTH",
            help="Allow running streamable-http transport without MCP client authentication. NOT recommended for production.",
        ),
    ] = False,
    document_url: Annotated[
        str | None,
        typer.Option(
            "--document-url",
            envvar="DOCUMENT_URL",
            help="The document URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer document URL.",
        ),
    ] = None,
    document_id: Annotated[
        str | None,
        typer.Option(
            "--document-id",
            envvar="DOCUMENT_ID",
            help="The document id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path. Optional - if omitted, you can list and select notebooks interactively.",
        ),
    ] = None,
    document_token: Annotated[
        str | None,
        typer.Option(
            "--document-token",
            envvar="DOCUMENT_TOKEN",
            help="The document token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
        ),
    ] = None,
    jupyter_url: Annotated[
        str | None,
        typer.Option(
            "--jupyter-url",
            envvar="JUPYTER_URL",
            help="The Jupyter URL to use as default for both document and runtime URLs. If not provided, individual URL settings take precedence.",
        ),
    ] = None,
    jupyter_token: Annotated[
        str | None,
        typer.Option(
            "--jupyter-token",
            envvar="JUPYTER_TOKEN",
            help="The Jupyter token to use as default for both document and runtime tokens. If not provided, individual token settings take precedence.",
        ),
    ] = None,
    allowed_jupyter_mcp_tools: Annotated[
        str,
        typer.Option(
            "--allowed-jupyter-mcp-tools",
            envvar="ALLOWED_JUPYTER_MCP_TOOLS",
            help="Comma-separated list of jupyter-mcp-tools to enable. Defaults to 'notebook_run-all-cells,notebook_get-selected-cell' - Only applicable when run as jupyter server extension.",
        ),
    ] = "notebook_run-all-cells,notebook_get-selected-cell",
    reconnect_interval: Annotated[
        int,
        typer.Option(
            "--reconnect-interval",
            envvar="RECONNECT_INTERVAL",
            min=0,
            help="Seconds to wait before reconnecting a dropped WebSocket connection to the kernel. Defaults to 0 (disabled).",
        ),
    ] = 0,
    execution_timeout: Annotated[
        int,
        typer.Option(
            "--execution-timeout",
            envvar="JUPYTER_MCP_EXECUTION_TIMEOUT",
            min=1,
            help="Default timeout in seconds for code execution, used when a tool call does not pass its own timeout. Defaults to 120.",
        ),
    ] = 120,
    max_execution_timeout: Annotated[
        int,
        typer.Option(
            "--max-execution-timeout",
            envvar="JUPYTER_MCP_MAX_EXECUTION_TIMEOUT",
            min=1,
            help="Maximum timeout in seconds a tool call may request for code execution. Defaults to 3600.",
        ),
    ] = 3600,
) -> None:
    """Manages Jupyter MCP Server."""
    if ctx.invoked_subcommand is not None:
        return

    _resolve_and_start(
        transport=transport,
        start_new_runtime=start_new_runtime,
        runtime_url=runtime_url,
        runtime_id=runtime_id,
        runtime_token=runtime_token,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        port=port,
        provider=provider,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
    )


def start_command(
    transport: Annotated[
        str,
        typer.Option(
            "--transport",
            envvar="TRANSPORT",
            click_type=click.Choice(["stdio", "streamable-http"]),
            help="The transport to use for the MCP server. Defaults to 'stdio'.",
        ),
    ] = "stdio",
    start_new_runtime: Annotated[
        bool,
        typer.Option(
            "--start-new-runtime",
            envvar="START_NEW_RUNTIME",
            click_type=click.BOOL,
            help="Start a new runtime or use an existing one.",
        ),
    ] = True,
    port: Annotated[
        int,
        typer.Option(
            "--port",
            envvar="PORT",
            help="The port to use for the Streamable HTTP transport. Ignored for stdio transport.",
        ),
    ] = 4040,
    otel_file: Annotated[
        str,
        typer.Option(
            "--otel-file",
            envvar="JUPYTER_MCP_OTEL_FILE",
            help="Path to JSONL file for OpenTelemetry span export.",
        ),
    ] = "",
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            envvar="PROVIDER",
            click_type=click.Choice(["jupyter", "datalayer"]),
            help="The provider to use for the document and runtime. Defaults to 'jupyter'.",
        ),
    ] = "jupyter",
    jupyterlab: Annotated[
        bool,
        typer.Option(
            "--jupyterlab",
            envvar="JUPYTERLAB",
            click_type=click.BOOL,
            help="Enable JupyterLab mode. Defaults to True.",
        ),
    ] = True,
    open_notebook_in_ui: Annotated[
        bool,
        typer.Option(
            "--open-notebook-in-ui",
            envvar="OPEN_NOTEBOOK_IN_UI",
            click_type=click.BOOL,
            help="Open the notebook in the JupyterLab UI when using it, which activates its tab. Defaults to False.",
        ),
    ] = False,
    runtime_url: Annotated[
        str | None,
        typer.Option(
            "--runtime-url",
            envvar="RUNTIME_URL",
            help="The runtime URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer runtime URL.",
        ),
    ] = None,
    runtime_id: Annotated[
        str | None,
        typer.Option(
            "--runtime-id",
            envvar="RUNTIME_ID",
            help="The kernel ID to use. If not provided, a new kernel should be started.",
        ),
    ] = None,
    runtime_token: Annotated[
        str | None,
        typer.Option(
            "--runtime-token",
            envvar="RUNTIME_TOKEN",
            help="The runtime token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
        ),
    ] = None,
    mcp_token: Annotated[
        str | None,
        typer.Option(
            "--mcp-token",
            envvar="MCP_TOKEN",
            help="Token for authenticating MCP clients (Bearer scheme). Required for streamable-http unless --insecure-mcp-noauth is set.",
        ),
    ] = None,
    insecure_mcp_noauth: Annotated[
        bool,
        typer.Option(
            "--insecure-mcp-noauth",
            envvar="INSECURE_MCP_NOAUTH",
            help="Allow running streamable-http transport without MCP client authentication. NOT recommended for production.",
        ),
    ] = False,
    document_url: Annotated[
        str | None,
        typer.Option(
            "--document-url",
            envvar="DOCUMENT_URL",
            help="The document URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer document URL.",
        ),
    ] = None,
    document_id: Annotated[
        str | None,
        typer.Option(
            "--document-id",
            envvar="DOCUMENT_ID",
            help="The document id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path. Optional - if omitted, you can list and select notebooks interactively.",
        ),
    ] = None,
    document_token: Annotated[
        str | None,
        typer.Option(
            "--document-token",
            envvar="DOCUMENT_TOKEN",
            help="The document token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
        ),
    ] = None,
    jupyter_url: Annotated[
        str | None,
        typer.Option(
            "--jupyter-url",
            envvar="JUPYTER_URL",
            help="The Jupyter URL to use as default for both document and runtime URLs. If not provided, individual URL settings take precedence.",
        ),
    ] = None,
    jupyter_token: Annotated[
        str | None,
        typer.Option(
            "--jupyter-token",
            envvar="JUPYTER_TOKEN",
            help="The Jupyter token to use as default for both document and runtime tokens. If not provided, individual token settings take precedence.",
        ),
    ] = None,
    allowed_jupyter_mcp_tools: Annotated[
        str,
        typer.Option(
            "--allowed-jupyter-mcp-tools",
            envvar="ALLOWED_JUPYTER_MCP_TOOLS",
            help="Comma-separated list of jupyter-mcp-tools to enable. Defaults to 'notebook_run-all-cells,notebook_get-selected-cell' - Only applicable when run as jupyter server extension.",
        ),
    ] = "notebook_run-all-cells,notebook_get-selected-cell",
    reconnect_interval: Annotated[
        int,
        typer.Option(
            "--reconnect-interval",
            envvar="RECONNECT_INTERVAL",
            min=0,
            help="Seconds to wait before reconnecting a dropped WebSocket connection to the kernel. Defaults to 0 (disabled).",
        ),
    ] = 0,
    execution_timeout: Annotated[
        int,
        typer.Option(
            "--execution-timeout",
            envvar="JUPYTER_MCP_EXECUTION_TIMEOUT",
            min=1,
            help="Default timeout in seconds for code execution, used when a tool call does not pass its own timeout. Defaults to 120.",
        ),
    ] = 120,
    max_execution_timeout: Annotated[
        int,
        typer.Option(
            "--max-execution-timeout",
            envvar="JUPYTER_MCP_MAX_EXECUTION_TIMEOUT",
            min=1,
            help="Maximum timeout in seconds a tool call may request for code execution. Defaults to 3600.",
        ),
    ] = 3600,
) -> None:
    """Start the Jupyter MCP server with a transport."""
    _resolve_and_start(
        transport=transport,
        start_new_runtime=start_new_runtime,
        runtime_url=runtime_url,
        runtime_id=runtime_id,
        runtime_token=runtime_token,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        port=port,
        provider=provider,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
    )
