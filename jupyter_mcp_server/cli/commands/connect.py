# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Connect command handler for the Typer CLI."""

from enum import Enum
from typing import Annotated

import httpx
import typer

from jupyter_mcp_server.config import get_config, set_config
from jupyter_mcp_server.log import logger
from jupyter_mcp_server.models import DocumentRuntime
from jupyter_mcp_server.utils import (
    mcp_auth_headers,
    parse_bool_option,
    resolve_url_and_token_variables,
)


class Provider(str, Enum):
    jupyter = "jupyter"
    datalayer = "datalayer"


def _update_extension_server_context(config) -> None:
    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context

        extension_context = get_server_context()
        extension_context.update(
            context_type="MCP_SERVER",
            serverapp=None,
            document_url=config.document_url,
            runtime_url=config.runtime_url,
            jupyterlab=config.jupyterlab,
        )
        logger.info(
            f"Updated jupyter_extension ServerContext with jupyterlab={config.jupyterlab}"
        )
    except Exception as error:
        logger.warning(f"Failed to update jupyter_extension ServerContext: {error}")


def connect_command(
    jupyter_mcp_server_url: Annotated[
        str,
        typer.Option(
            "--jupyter-mcp-server-url",
            envvar="JUPYTER_MCP_SERVER_URL",
            help="The URL of the Jupyter MCP Server to connect to. Defaults to 'http://localhost:4040'.",
        ),
    ] = "http://localhost:4040",
    provider: Annotated[
        Provider,
        typer.Option("--provider", envvar="PROVIDER"),
    ] = Provider.jupyter,
    jupyterlab: Annotated[
        str,
        typer.Option("--jupyterlab", envvar="JUPYTERLAB"),
    ] = "True",
    open_notebook_in_ui: Annotated[
        str,
        typer.Option("--open-notebook-in-ui", envvar="OPEN_NOTEBOOK_IN_UI"),
    ] = "False",
    runtime_url: Annotated[
        str | None,
        typer.Option("--runtime-url", envvar="RUNTIME_URL"),
    ] = None,
    runtime_id: Annotated[
        str | None,
        typer.Option("--runtime-id", envvar="RUNTIME_ID"),
    ] = None,
    runtime_token: Annotated[
        str | None,
        typer.Option("--runtime-token", envvar="RUNTIME_TOKEN"),
    ] = None,
    mcp_token: Annotated[
        str | None,
        typer.Option("--mcp-token", envvar="MCP_TOKEN"),
    ] = None,
    document_url: Annotated[
        str | None,
        typer.Option("--document-url", envvar="DOCUMENT_URL"),
    ] = None,
    document_id: Annotated[
        str | None,
        typer.Option("--document-id", envvar="DOCUMENT_ID"),
    ] = None,
    document_token: Annotated[
        str | None,
        typer.Option("--document-token", envvar="DOCUMENT_TOKEN"),
    ] = None,
    jupyter_url: Annotated[
        str | None,
        typer.Option("--jupyter-url", envvar="JUPYTER_URL"),
    ] = None,
    jupyter_token: Annotated[
        str | None,
        typer.Option("--jupyter-token", envvar="JUPYTER_TOKEN"),
    ] = None,
    insecure_mcp_noauth: Annotated[
        bool,
        typer.Option("--insecure-mcp-noauth", envvar="INSECURE_MCP_NOAUTH"),
    ] = False,
    allowed_jupyter_mcp_tools: Annotated[
        str,
        typer.Option(
            "--allowed-jupyter-mcp-tools",
            envvar="ALLOWED_JUPYTER_MCP_TOOLS",
        ),
    ] = "notebook_run-all-cells,notebook_get-selected-cell",
    reconnect_interval: Annotated[
        int,
        typer.Option("--reconnect-interval", envvar="RECONNECT_INTERVAL", min=0),
    ] = 0,
    execution_timeout: Annotated[
        int,
        typer.Option(
            "--execution-timeout",
            envvar="JUPYTER_MCP_EXECUTION_TIMEOUT",
            min=1,
        ),
    ] = 120,
    max_execution_timeout: Annotated[
        int,
        typer.Option(
            "--max-execution-timeout",
            envvar="JUPYTER_MCP_MAX_EXECUTION_TIMEOUT",
            min=1,
        ),
    ] = 3600,
) -> None:
    """Command to connect a Jupyter MCP Server to a document and a runtime."""

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

    config = set_config(
        provider=provider.value,
        runtime_url=resolved_runtime_url,
        runtime_id=runtime_id,
        runtime_token=resolved_runtime_token,
        document_url=resolved_document_url,
        document_id=document_id,
        document_token=resolved_document_token,
        jupyterlab=parse_bool_option(jupyterlab, "--jupyterlab"),
        open_notebook_in_ui=parse_bool_option(
            open_notebook_in_ui, "--open-notebook-in-ui"
        ),
    )

    _update_extension_server_context(config)

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

    response = httpx.put(
        f"{jupyter_mcp_server_url}/api/connect",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **mcp_auth_headers(mcp_token),
        },
        content=document_runtime.model_dump_json(),
    )
    response.raise_for_status()
