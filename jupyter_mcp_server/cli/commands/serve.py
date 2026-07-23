# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Serve/start command handlers for the Typer CLI."""

from enum import Enum
from typing import Annotated

import typer

from jupyter_mcp_server.cli.commands.connect import Provider
from jupyter_mcp_server.utils import (
    do_start,
    parse_bool_option,
    resolve_url_and_token_variables,
)


class Transport(str, Enum):
    """Supported MCP server transports."""

    stdio = "stdio"
    streamable_http = "streamable-http"


def _resolve_and_start(
    transport: str,
    start_new_runtime: str,
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
    jupyterlab: str,
    open_notebook_in_ui: str,
    allowed_jupyter_mcp_tools: str,
    otel_file: str,
    reconnect_interval: int,
    execution_timeout: int,
    max_execution_timeout: int,
    sandbox_variant: str = "jupyter",
    enable_sandboxes: bool = False,
    runtime_proxy_token: str | None = None,
    runtime_use_browser_bridge: bool = False,
    sandbox_environment: str | None = None,
    sandbox_gpu: str | None = None,
) -> None:
    (
        resolved_document_url,
        resolved_document_token,
        resolved_runtime_url,
        resolved_runtime_token,
    ) = resolve_url_and_token_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        runtime_url=runtime_url,
        runtime_token=runtime_token,
    )

    do_start(
        transport=transport,
        start_new_runtime=parse_bool_option(start_new_runtime, "--start-new-runtime"),
        runtime_url=resolved_runtime_url,
        runtime_id=runtime_id,
        runtime_token=resolved_runtime_token,
        document_url=resolved_document_url,
        document_id=document_id,
        document_token=resolved_document_token,
        port=port,
        provider=provider,
        jupyterlab=parse_bool_option(jupyterlab, "--jupyterlab"),
        open_notebook_in_ui=parse_bool_option(open_notebook_in_ui, "--open-notebook-in-ui"),
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
        sandbox_variant=sandbox_variant,
        enable_sandboxes=enable_sandboxes,
        runtime_proxy_token=runtime_proxy_token,
        runtime_use_browser_bridge=runtime_use_browser_bridge,
        sandbox_environment=sandbox_environment,
        sandbox_gpu=sandbox_gpu,
    )


def server_callback(
    ctx: typer.Context,
    transport: Annotated[
        Transport,
        typer.Option(
            "--transport",
            envvar="TRANSPORT",
            help="The transport to use for the MCP server. Defaults to 'stdio'.",
        ),
    ] = Transport.stdio,
    start_new_runtime: Annotated[
        str,
        typer.Option(
            "--start-new-runtime",
            envvar="START_NEW_RUNTIME",
            help="Start a new runtime or use an existing one.",
        ),
    ] = "True",
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
        Provider,
        typer.Option(
            "--provider",
            envvar="PROVIDER",
            help="The provider to use for the document and runtime. Defaults to 'jupyter'.",
        ),
    ] = Provider.jupyter,
    jupyterlab: Annotated[
        str,
        typer.Option(
            "--jupyterlab",
            envvar="JUPYTERLAB",
            help="Enable JupyterLab mode. Defaults to True.",
        ),
    ] = "True",
    open_notebook_in_ui: Annotated[
        str,
        typer.Option(
            "--open-notebook-in-ui",
            envvar="OPEN_NOTEBOOK_IN_UI",
            help="Open the notebook in the JupyterLab UI when using it, which activates its tab. Defaults to False.",
        ),
    ] = "False",
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
    sandbox_variant: Annotated[
        str,
        typer.Option(
            "--sandbox-variant",
            envvar="SANDBOX_VARIANT",
            help="Code execution sandbox variant. 'jupyter' (default) uses jupyter-kernel-client directly. Other values ('colab', 'monty', 'modal', 'docker', 'eval', 'datalayer') route execution through the code-sandboxes package.",
        ),
    ] = "jupyter",
    enable_sandboxes: Annotated[
        bool,
        typer.Option(
            "--enable-sandboxes/--disable-sandboxes",
            envvar="ENABLE_SANDBOXES",
            help="Enable sandbox lifecycle tools and sandbox-backed execution routes.",
        ),
    ] = False,
    runtime_proxy_token: Annotated[
        str | None,
        typer.Option(
            "--runtime-proxy-token",
            envvar="RUNTIME_PROXY_TOKEN",
            help="Proxy token used by the 'colab' sandbox variant (colab-runtime-proxy-token).",
        ),
    ] = None,
    sandbox_environment: Annotated[
        str | None,
        typer.Option(
            "--sandbox-environment",
            envvar="SANDBOX_ENVIRONMENT",
            help="Environment name for cloud sandboxes (e.g. Datalayer/Modal).",
        ),
    ] = None,
    sandbox_gpu: Annotated[
        str | None,
        typer.Option(
            "--sandbox-gpu",
            envvar="SANDBOX_GPU",
            help="GPU flavor for sandbox engines that support it (e.g. Modal/Datalayer: T4, A10G, A100, H100).",
        ),
    ] = None,
    runtime_use_browser_bridge: Annotated[
        bool,
        typer.Option(
            "--runtime-use-browser-bridge/--no-runtime-use-browser-bridge",
            envvar="RUNTIME_USE_BROWSER_BRIDGE",
            help="For the 'colab' sandbox variant, obtain the runtime connection details from an authenticated Colab browser session via jupyter-kernel-client's browser bridge.",
        ),
    ] = False,
) -> None:
    """Manages Jupyter MCP Server."""
    if ctx.invoked_subcommand is not None:
        return

    _resolve_and_start(
        transport=transport.value,
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
        provider=provider.value,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
        sandbox_variant=sandbox_variant,
        enable_sandboxes=enable_sandboxes,
        runtime_proxy_token=runtime_proxy_token,
        runtime_use_browser_bridge=runtime_use_browser_bridge,
        sandbox_environment=sandbox_environment,
        sandbox_gpu=sandbox_gpu,
    )


def start_command(
    transport: Annotated[
        Transport,
        typer.Option(
            "--transport",
            envvar="TRANSPORT",
            help="The transport to use for the MCP server. Defaults to 'stdio'.",
        ),
    ] = Transport.stdio,
    start_new_runtime: Annotated[
        str,
        typer.Option(
            "--start-new-runtime",
            envvar="START_NEW_RUNTIME",
            help="Start a new runtime or use an existing one.",
        ),
    ] = "True",
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
        Provider,
        typer.Option(
            "--provider",
            envvar="PROVIDER",
            help="The provider to use for the document and runtime. Defaults to 'jupyter'.",
        ),
    ] = Provider.jupyter,
    jupyterlab: Annotated[
        str,
        typer.Option(
            "--jupyterlab",
            envvar="JUPYTERLAB",
            help="Enable JupyterLab mode. Defaults to True.",
        ),
    ] = "True",
    open_notebook_in_ui: Annotated[
        str,
        typer.Option(
            "--open-notebook-in-ui",
            envvar="OPEN_NOTEBOOK_IN_UI",
            help="Open the notebook in the JupyterLab UI when using it, which activates its tab. Defaults to False.",
        ),
    ] = "False",
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
    sandbox_variant: Annotated[
        str,
        typer.Option(
            "--sandbox-variant",
            envvar="SANDBOX_VARIANT",
            help="Code execution sandbox variant. 'jupyter' (default) uses jupyter-kernel-client directly. Other values ('colab', 'monty', 'modal', 'docker', 'eval', 'datalayer') route execution through the code-sandboxes package.",
        ),
    ] = "jupyter",
    enable_sandboxes: Annotated[
        bool,
        typer.Option(
            "--enable-sandboxes/--disable-sandboxes",
            envvar="ENABLE_SANDBOXES",
            help="Enable sandbox lifecycle tools and sandbox-backed execution routes.",
        ),
    ] = False,
    runtime_proxy_token: Annotated[
        str | None,
        typer.Option(
            "--runtime-proxy-token",
            envvar="RUNTIME_PROXY_TOKEN",
            help="Proxy token used by the 'colab' sandbox variant (colab-runtime-proxy-token).",
        ),
    ] = None,
    sandbox_environment: Annotated[
        str | None,
        typer.Option(
            "--sandbox-environment",
            envvar="SANDBOX_ENVIRONMENT",
            help="Environment name for cloud sandboxes (e.g. Datalayer/Modal).",
        ),
    ] = None,
    sandbox_gpu: Annotated[
        str | None,
        typer.Option(
            "--sandbox-gpu",
            envvar="SANDBOX_GPU",
            help="GPU flavor for sandbox engines that support it (e.g. Modal/Datalayer: T4, A10G, A100, H100).",
        ),
    ] = None,
    runtime_use_browser_bridge: Annotated[
        bool,
        typer.Option(
            "--runtime-use-browser-bridge/--no-runtime-use-browser-bridge",
            envvar="RUNTIME_USE_BROWSER_BRIDGE",
            help="For the 'colab' sandbox variant, obtain the runtime connection details from an authenticated Colab browser session via jupyter-kernel-client's browser bridge.",
        ),
    ] = False,
) -> None:
    """Start the Jupyter MCP Server with a transport."""
    _resolve_and_start(
        transport=transport.value,
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
        provider=provider.value,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
        sandbox_variant=sandbox_variant,
        enable_sandboxes=enable_sandboxes,
        runtime_proxy_token=runtime_proxy_token,
        runtime_use_browser_bridge=runtime_use_browser_bridge,
        sandbox_environment=sandbox_environment,
        sandbox_gpu=sandbox_gpu,
    )
