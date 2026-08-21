# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Serve/start command handlers for the Typer CLI."""

from enum import Enum
from typing import Annotated

import typer

from jupyter_mcp_server.cli.commands.connect import DocumentProvider
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
    start_new_code_sandbox: str,
    code_sandbox_url: str | None,
    code_sandbox_id: str | None,
    code_sandbox_token: str | None,
    code_sandbox_password: str | None,
    mcp_token: str | None,
    insecure_mcp_noauth: bool,
    document_url: str | None,
    document_id: str | None,
    document_token: str | None,
    document_password: str | None,
    jupyter_url: str | None,
    jupyter_token: str | None,
    jupyter_password: str | None,
    port: int,
    document_provider: str,
    jupyterlab: str,
    open_notebook_in_ui: str,
    allowed_jupyter_mcp_tools: str,
    otel_file: str,
    reconnect_interval: int,
    execution_timeout: int,
    max_execution_timeout: int,
    sandbox_variant: str = "jupyter-server",
    code_sandbox_proxy_token: str | None = None,
    code_sandbox_channels_url: str | None = None,
    sandbox_environment: str | None = None,
    sandbox_gpu: str | None = None,
) -> None:
    (
        resolved_document_url,
        resolved_document_token,
        resolved_code_sandbox_url,
        resolved_code_sandbox_token,
    ) = resolve_url_and_token_variables(
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        document_url=document_url,
        document_token=document_token,
        code_sandbox_url=code_sandbox_url,
        code_sandbox_token=code_sandbox_token,
    )

    # Passwords mirror the token precedence: an individual --{code sandbox,document}-password
    # wins, otherwise the shared --jupyter-password is used as the fallback. Passwords
    # take precedence over tokens at the auth layer (see JupyterPasswordAuth).
    resolved_document_password = document_password or jupyter_password
    resolved_code_sandbox_password = code_sandbox_password or jupyter_password

    do_start(
        transport=transport,
        start_new_code_sandbox=parse_bool_option(start_new_code_sandbox, "--start-new-code-sandbox"),
        code_sandbox_url=resolved_code_sandbox_url,
        code_sandbox_id=code_sandbox_id,
        code_sandbox_token=resolved_code_sandbox_token,
        code_sandbox_password=resolved_code_sandbox_password,
        document_url=resolved_document_url,
        document_id=document_id,
        document_token=resolved_document_token,
        document_password=resolved_document_password,
        port=port,
        document_provider=document_provider,
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
        code_sandbox_proxy_token=code_sandbox_proxy_token,
        code_sandbox_channels_url=code_sandbox_channels_url,
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
    start_new_code_sandbox: Annotated[
        str,
        typer.Option(
            "--start-new-code-sandbox",
            envvar="START_NEW_CODE_SANDBOX",
            help="Start a new code sandbox or use an existing one.",
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
    document_provider: Annotated[
        DocumentProvider,
        typer.Option(
            "--document-provider",
            # `--provider` / PROVIDER stay accepted: they named this before v1.3.2.
            "--provider",
            envvar=["DOCUMENT_PROVIDER", "PROVIDER"],
            help=(
                "Which backend holds the notebook documents. `jupyter` talks to "
                "the collaboration API of a Jupyter Server, `datalayer` to the "
                "Datalayer spacer. Execution is chosen separately with "
                "--sandbox-variant. Defaults to 'jupyter'."
            ),
        ),
    ] = DocumentProvider.jupyter,
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
    code_sandbox_url: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-url",
            envvar="CODE_SANDBOX_URL",
            help="The code sandbox URL to use. With the jupyter document backend, this is the Jupyter server URL. With the datalayer one, this is the Datalayer code sandbox URL.",
        ),
    ] = None,
    code_sandbox_id: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-id",
            envvar="CODE_SANDBOX_ID",
            help="The kernel ID to use. If not provided, a new kernel should be started.",
        ),
    ] = None,
    code_sandbox_token: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-token",
            envvar="CODE_SANDBOX_TOKEN",
            help="The code sandbox token to use for authentication with the backend. If not provided, the backend should accept anonymous requests.",
        ),
    ] = None,
    code_sandbox_password: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-password",
            envvar="CODE_SANDBOX_PASSWORD",
            help="Password for code sandbox Jupyter server authentication. Takes precedence over --code-sandbox-token if both are set.",
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
            help="The document URL to use. With the jupyter document backend, this is the Jupyter server URL. With the datalayer one, this is the Datalayer document URL.",
        ),
    ] = None,
    document_id: Annotated[
        str | None,
        typer.Option(
            "--document-id",
            envvar="DOCUMENT_ID",
            help="The document id to use. With the jupyter document backend, this is the notebook path. With the datalayer one, this is the notebook path. Optional - if omitted, you can list and select notebooks interactively.",
        ),
    ] = None,
    document_token: Annotated[
        str | None,
        typer.Option(
            "--document-token",
            envvar="DOCUMENT_TOKEN",
            help="The document token to use for authentication with the backend. If not provided, the backend should accept anonymous requests.",
        ),
    ] = None,
    document_password: Annotated[
        str | None,
        typer.Option(
            "--document-password",
            envvar="DOCUMENT_PASSWORD",
            help="Password for document Jupyter server authentication. Takes precedence over --document-token if both are set.",
        ),
    ] = None,
    jupyter_url: Annotated[
        str | None,
        typer.Option(
            "--jupyter-url",
            envvar="JUPYTER_URL",
            help="The Jupyter URL to use as default for both document and code sandbox URLs. If not provided, individual URL settings take precedence.",
        ),
    ] = None,
    jupyter_token: Annotated[
        str | None,
        typer.Option(
            "--jupyter-token",
            envvar="JUPYTER_TOKEN",
            help="The Jupyter token to use as default for both document and code sandbox tokens. If not provided, individual token settings take precedence.",
        ),
    ] = None,
    jupyter_password: Annotated[
        str | None,
        typer.Option(
            "--jupyter-password",
            envvar="JUPYTER_PASSWORD",
            help="Shared password for both code sandbox and document servers (fallback if individual passwords not set). Takes precedence over --jupyter-token if both are set.",
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
            help="Code execution sandbox variant. 'jupyter-server' (default) uses the code-sandboxes Jupyter Server engine. Other values ('google-colab', 'kaggle', 'monty', 'modal', 'docker', 'eval', 'daytona', 'e2b', 'coreweave', 'cloudflare', 'datalayer') route execution through the code-sandboxes package. Spelling is not fussy: 'google_colab' names the same variant as 'google-colab'.",
        ),
    ] = "jupyter-server",
    code_sandbox_proxy_token: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-proxy-token",
            envvar="CODE_SANDBOX_PROXY_TOKEN",
            help="Proxy token used by the Google Colab sandbox variant (colab-runtime-proxy-token).",
        ),
    ] = None,
    code_sandbox_channels_url: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-channels-url",
            envvar="CODE_SANDBOX_CHANNELS_URL",
            help="For the 'google-colab' and 'kaggle' sandbox variants, WebSocket channels URL used to derive code sandbox URL and kernel id.",
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
            help=(
                "GPU flavor / accelerator for sandbox engines that support it "
                "(Modal/Datalayer examples: T4, A10G, A100, H100; "
                "Daytona examples: H100, H200, RTX-4090; CoreWeave example: H100; "
                "Kaggle batch examples: NvidiaTeslaT4, NvidiaTeslaP100, or aliases T4/P100)."
            ),
        ),
    ] = None,
) -> None:
    """Manages Jupyter MCP Server."""
    if ctx.invoked_subcommand is not None:
        return

    _resolve_and_start(
        transport=transport.value,
        start_new_code_sandbox=start_new_code_sandbox,
        code_sandbox_url=code_sandbox_url,
        code_sandbox_id=code_sandbox_id,
        code_sandbox_token=code_sandbox_token,
        code_sandbox_password=code_sandbox_password,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        document_password=document_password,
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        jupyter_password=jupyter_password,
        port=port,
        document_provider=document_provider.value,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
        sandbox_variant=sandbox_variant,
        code_sandbox_proxy_token=code_sandbox_proxy_token,
        code_sandbox_channels_url=code_sandbox_channels_url,
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
    start_new_code_sandbox: Annotated[
        str,
        typer.Option(
            "--start-new-code-sandbox",
            envvar="START_NEW_CODE_SANDBOX",
            help="Start a new code sandbox or use an existing one.",
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
    document_provider: Annotated[
        DocumentProvider,
        typer.Option(
            "--document-provider",
            # `--provider` / PROVIDER stay accepted: they named this before v1.3.2.
            "--provider",
            envvar=["DOCUMENT_PROVIDER", "PROVIDER"],
            help=(
                "Which backend holds the notebook documents. `jupyter` talks to "
                "the collaboration API of a Jupyter Server, `datalayer` to the "
                "Datalayer spacer. Execution is chosen separately with "
                "--sandbox-variant. Defaults to 'jupyter'."
            ),
        ),
    ] = DocumentProvider.jupyter,
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
    code_sandbox_url: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-url",
            envvar="CODE_SANDBOX_URL",
            help="The code sandbox URL to use. With the jupyter document backend, this is the Jupyter server URL. With the datalayer one, this is the Datalayer code sandbox URL.",
        ),
    ] = None,
    code_sandbox_id: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-id",
            envvar="CODE_SANDBOX_ID",
            help="The kernel ID to use. If not provided, a new kernel should be started.",
        ),
    ] = None,
    code_sandbox_token: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-token",
            envvar="CODE_SANDBOX_TOKEN",
            help="The code sandbox token to use for authentication with the backend. If not provided, the backend should accept anonymous requests.",
        ),
    ] = None,
    code_sandbox_password: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-password",
            envvar="CODE_SANDBOX_PASSWORD",
            help="Password for code sandbox Jupyter server authentication. Takes precedence over --code-sandbox-token if both are set.",
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
            help="The document URL to use. With the jupyter document backend, this is the Jupyter server URL. With the datalayer one, this is the Datalayer document URL.",
        ),
    ] = None,
    document_id: Annotated[
        str | None,
        typer.Option(
            "--document-id",
            envvar="DOCUMENT_ID",
            help="The document id to use. With the jupyter document backend, this is the notebook path. With the datalayer one, this is the notebook path. Optional - if omitted, you can list and select notebooks interactively.",
        ),
    ] = None,
    document_token: Annotated[
        str | None,
        typer.Option(
            "--document-token",
            envvar="DOCUMENT_TOKEN",
            help="The document token to use for authentication with the backend. If not provided, the backend should accept anonymous requests.",
        ),
    ] = None,
    document_password: Annotated[
        str | None,
        typer.Option(
            "--document-password",
            envvar="DOCUMENT_PASSWORD",
            help="Password for document Jupyter server authentication. Takes precedence over --document-token if both are set.",
        ),
    ] = None,
    jupyter_url: Annotated[
        str | None,
        typer.Option(
            "--jupyter-url",
            envvar="JUPYTER_URL",
            help="The Jupyter URL to use as default for both document and code sandbox URLs. If not provided, individual URL settings take precedence.",
        ),
    ] = None,
    jupyter_token: Annotated[
        str | None,
        typer.Option(
            "--jupyter-token",
            envvar="JUPYTER_TOKEN",
            help="The Jupyter token to use as default for both document and code sandbox tokens. If not provided, individual token settings take precedence.",
        ),
    ] = None,
    jupyter_password: Annotated[
        str | None,
        typer.Option(
            "--jupyter-password",
            envvar="JUPYTER_PASSWORD",
            help="Shared password for both code sandbox and document servers (fallback if individual passwords not set). Takes precedence over --jupyter-token if both are set.",
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
            help="Code execution sandbox variant. 'jupyter-server' (default) uses the code-sandboxes Jupyter Server engine. Other values ('google-colab', 'kaggle', 'monty', 'modal', 'docker', 'eval', 'daytona', 'e2b', 'coreweave', 'cloudflare', 'datalayer') route execution through the code-sandboxes package. Spelling is not fussy: 'google_colab' names the same variant as 'google-colab'.",
        ),
    ] = "jupyter-server",
    code_sandbox_proxy_token: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-proxy-token",
            envvar="CODE_SANDBOX_PROXY_TOKEN",
            help="Proxy token used by the Google Colab sandbox variant (colab-runtime-proxy-token).",
        ),
    ] = None,
    code_sandbox_channels_url: Annotated[
        str | None,
        typer.Option(
            "--code-sandbox-channels-url",
            envvar="CODE_SANDBOX_CHANNELS_URL",
            help="For the 'google-colab' and 'kaggle' sandbox variants, WebSocket channels URL used to derive code sandbox URL and kernel id.",
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
            help=(
                "GPU flavor / accelerator for sandbox engines that support it "
                "(Modal/Datalayer examples: T4, A10G, A100, H100; "
                "Daytona examples: H100, H200, RTX-4090; CoreWeave example: H100; "
                "Kaggle batch examples: NvidiaTeslaT4, NvidiaTeslaP100, or aliases T4/P100)."
            ),
        ),
    ] = None,
) -> None:
    """Start the Jupyter MCP Server with a transport."""
    _resolve_and_start(
        transport=transport.value,
        start_new_code_sandbox=start_new_code_sandbox,
        code_sandbox_url=code_sandbox_url,
        code_sandbox_id=code_sandbox_id,
        code_sandbox_token=code_sandbox_token,
        code_sandbox_password=code_sandbox_password,
        mcp_token=mcp_token,
        insecure_mcp_noauth=insecure_mcp_noauth,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        document_password=document_password,
        jupyter_url=jupyter_url,
        jupyter_token=jupyter_token,
        jupyter_password=jupyter_password,
        port=port,
        document_provider=document_provider.value,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        otel_file=otel_file,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
        sandbox_variant=sandbox_variant,
        code_sandbox_proxy_token=code_sandbox_proxy_token,
        code_sandbox_channels_url=code_sandbox_channels_url,
        sandbox_environment=sandbox_environment,
        sandbox_gpu=sandbox_gpu,
    )
