# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import logging
from typing import Union

import click
import httpx
import uvicorn

from fastapi import Request
from starlette.responses import JSONResponse

from mcp.server import FastMCP

from jupyter_kernel_client import KernelClient
from jupyter_nbmodel_client import (
    NbModelClient,
    get_notebook_websocket_url,
)
from jupyter_mcp_server.models import RoomRuntime
from jupyter_mcp_server.utils import extract_output


logger = logging.getLogger(__name__)


TRANSPORT: str = "stdio"
PROVIDER: str = "jupyter"

RUNTIME_URL: str = "http://localhost:8888"
START_NEW_RUNTIME: bool = False
RUNTIME_ID: str | None = None
RUNTIME_TOKEN: str | None = None

ROOM_URL: str = "http://localhost:8888"
ROOM_ID: str = "notebook.ipynb"
ROOM_TOKEN: str | None = None


mcp = FastMCP(name="Jupyter MCP Server", json_response=False, stateless_http=True)


kernel = None


###############################################################################
# 


def _start_kernel():
        """Start the Jupyter kernel."""
        global kernel
        if kernel:
            kernel.stop()
        # Initialize the kernel client with the provided parameters.
        kernel = KernelClient(server_url=RUNTIME_URL, token=RUNTIME_TOKEN, kernel_id=RUNTIME_ID)
        kernel.start()


###############################################################################
# Custom Routes.


@mcp.custom_route("/api/connect", ["PUT"])
async def connect(request: Request):
    """Connect to a room and a runtime from the Jupyter MCP server."""

    data = await request.json()
    logger.info("Connecting to room_runtime:", data)

    room_runtime = RoomRuntime(**data)

    global kernel
    if kernel:
        kernel.stop()

    global PROVIDER
    PROVIDER = room_runtime.provider

    global RUNTIME_URL
    RUNTIME_URL = room_runtime.runtime_url
    global RUNTIME_ID
    RUNTIME_ID = room_runtime.runtime_id
    global RUNTIME_TOKEN
    RUNTIME_TOKEN = room_runtime.runtime_token

    global ROOM_URL
    ROOM_URL = room_runtime.room_url
    global ROOM_ID
    ROOM_ID = room_runtime.room_id
    global ROOM_TOKEN
    ROOM_TOKEN = room_runtime.room_token

    _start_kernel()

    return JSONResponse({ "success": True })


@mcp.custom_route("/api/healthz", ["GET"])
async def health_check():
    """Custom health check endpoint"""
    return JSONResponse({
        "success": True,
        "service": "jupyter-mcp-server",
        "message": "Jupyter MCP Server is running.",
        "status": "healthy",
    })


###############################################################################
# Tools.


# TODO: Add clear_outputs(cell_index: int) tool.
# We need to expose reset_cell in NbModelClient:
# https://github.com/datalayer/jupyter-nbmodel-client/blob/main/jupyter_nbmodel_client/model.py#L297-L301


@mcp.tool()
async def append_markdown_cell(cell_source: str) -> str:
    """Append at the end of the notebook a markdown cell with the provided source.

    Args:
        cell_source: Markdown source

    Returns:
        str: Success message
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()
    notebook.add_markdown_cell(cell_source)
    await notebook.stop()
    return "Jupyter Markdown cell added."


@mcp.tool()
async def insert_markdown_cell(cell_index: int, cell_source: str) -> str:
    """Insert a markdown cell in a Jupyter notebook.

    Args:
        cell_index: Index of the cell to insert (0-based)
        cell_source: Markdown source

    Returns:
        str: Success message
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()
    notebook.insert_markdown_cell(cell_index, cell_source)
    await notebook.stop()
    return f"Jupyter Markdown cell {cell_index} inserted."


@mcp.tool()
async def overwrite_cell_source(cell_index: int, cell_source: str) -> str:
    """Overwrite the source of an existing cell.
       Note this does not execute the modified cell by itself.

    Args:
        cell_index: Index of the cell to overwrite (0-based)
        cell_source: New cell source - must match existing cell type

    Returns:
        str: Success message
    """
    # TODO: Add check on cell_type
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()
    notebook.set_cell_source(cell_index, cell_source)
    await notebook.stop()
    return f"Cell {cell_index} overwritten successfully - use execute_cell to execute it if code"


@mcp.tool()
async def append_execute_code_cell(cell_source: str) -> list[str]:
    """Append at the end of the notebook a code cell with the provided source and execute it.

    Args:
        cell_source: Code source

    Returns:
        list[str]: List of outputs from the executed cell
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()
    cell_index = notebook.add_code_cell(cell_source)
    notebook.execute_cell(cell_index, kernel)

    ydoc = notebook._doc
    outputs = ydoc._ycells[cell_index]["outputs"]
    outputs_str = [extract_output(output) for output in outputs]

    await notebook.stop()

    return outputs_str


@mcp.tool()
async def insert_execute_code_cell(cell_index: int, cell_source: str) -> list[str]:
    """Insert and execute a code cell in a Jupyter notebook.

    Args:
        cell_index: Index of the cell to insert (0-based)
        cell_source: Code source

    Returns:
        list[str]: List of outputs from the executed cell
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()
    notebook.insert_code_cell(cell_index, cell_source)
    notebook.execute_cell(cell_index, kernel)

    ydoc = notebook._doc
    outputs = ydoc._ycells[cell_index]["outputs"]
    outputs_str = [extract_output(output) for output in outputs]

    await notebook.stop()

    return outputs_str


@mcp.tool()
async def execute_cell(cell_index: int) -> list[str]:
    """Execute a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to execute (0-based)
    Returns:
        list[str]: List of outputs from the executed cell
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()

    ydoc = notebook._doc

    if cell_index < 0 or cell_index >= len(ydoc._ycells):
        await notebook.stop()
        raise ValueError(
            f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
        )

    notebook.execute_cell(cell_index, kernel)

    ydoc = notebook._doc
    outputs = ydoc._ycells[cell_index]["outputs"]
    outputs_str = [extract_output(output) for output in outputs]

    await notebook.stop()
    return outputs_str


@mcp.tool()
async def read_all_cells() -> list[dict[str, Union[str, int, list[str]]]]:
    """Read all cells from the Jupyter notebook.
    Returns:
        list[dict]: List of cell information including index, type, source,
                    and outputs (for code cells)
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()

    ydoc = notebook._doc
    cells = []

    for i, cell in enumerate(ydoc._ycells):
        cell_info = {
            "index": i,
            "type": cell.get("cell_type", "unknown"),
            "source": cell.get("source", ""),
        }

        # Add outputs for code cells
        if cell.get("cell_type") == "code":
            outputs = cell.get("outputs", [])
            cell_info["outputs"] = [extract_output(output) for output in outputs]

        cells.append(cell_info)

    await notebook.stop()
    return cells


@mcp.tool()
async def read_cell(cell_index: int) -> dict[str, Union[str, int, list[str]]]:
    """Read a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to read (0-based)
    Returns:
        dict: Cell information including index, type, source, and outputs (for code cells)
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()

    ydoc = notebook._doc

    if cell_index < 0 or cell_index >= len(ydoc._ycells):
        await notebook.stop()
        raise ValueError(
            f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
        )

    cell = ydoc._ycells[cell_index]
    cell_info = {
        "index": cell_index,
        "type": cell.get("cell_type", "unknown"),
        "source": cell.get("source", ""),
    }

    # Add outputs for code cells
    if cell.get("cell_type") == "code":
        outputs = cell.get("outputs", [])
        cell_info["outputs"] = [extract_output(output) for output in outputs]

    await notebook.stop()
    return cell_info


@mcp.tool()
async def get_notebook_info() -> dict[str, Union[str, int, dict[str, int]]]:
    """Get basic information about the notebook.
    Returns:
        dict: Notebook information including path, total cells, and cell type counts
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()

    ydoc = notebook._doc
    total_cells: int = len(ydoc._ycells)

    cell_types: dict[str, int] = {}
    for cell in ydoc._ycells:
        cell_type: str = str(cell.get("cell_type", "unknown"))
        cell_types[cell_type] = cell_types.get(cell_type, 0) + 1

    # TODO: We could also get notebook metadata
    # e.g. to know the language if using different kernels
    info: dict[str, Union[str, int, dict[str, int]]] = {
        "room_id": ROOM_ID,
        "total_cells": total_cells,
        "cell_types": cell_types,
    }

    await notebook.stop()
    return info


@mcp.tool()
async def delete_cell(cell_index: int) -> str:
    """Delete a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to delete (0-based)
    Returns:
        str: Success message
    """
    notebook = NbModelClient(
        get_notebook_websocket_url(server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER)
    )
    await notebook.start()

    ydoc = notebook._doc

    if cell_index < 0 or cell_index >= len(ydoc._ycells):
        await notebook.stop()
        raise ValueError(
            f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
        )

    cell_type = ydoc._ycells[cell_index].get("cell_type", "unknown")

    # Delete the cell
    del ydoc._ycells[cell_index]

    await notebook.stop()
    return f"Cell {cell_index} ({cell_type}) deleted successfully."


###############################################################################
# Commands.


@click.group()
def server():
    """Manages Jupyter MCP Server."""
    pass


@server.command("connect")
@click.option("--provider", envvar="PROVIDER", type=click.Choice(["jupyter", "datalayer"]), default="jupyter", help="The provider to use for the room and runtime. Defaults to 'jupyter'.")
@click.option("--runtime-url", envvar="RUNTIME_URL", type=click.STRING, default="http://localhost:8888", help="The runtime URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer runtime URL.") 
@click.option("--runtime-id", envvar="RUNTIME_ID", type=click.STRING, default=None, help="The kernel ID to use. If not provided, a new kernel should be started.")
@click.option("--runtime-token", envvar="RUNTIME_TOKEN", type=click.STRING, default=None, help="The runtime token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.")
@click.option("--room-url", envvar="ROOM_URL", type=click.STRING, default="http://localhost:8888", help="The room URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer room URL.") 
@click.option("--room-id", envvar="ROOM_ID", type=click.STRING, default="notebook.ipynb", help="The room id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path.")
@click.option("--room-token", envvar="ROOM_TOKEN", type=click.STRING, default=None, help="The room token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.")
@click.option("--jupyter-mcp-server-url", envvar="JUPYTER_MCP_SERVER_URL", type=click.STRING, default="http://localhost:4040", help="The URL of the Jupyter MCP Server to connect to. Defaults to 'http://localhost:4040'.")
def connect_command(jupyter_mcp_server_url: str, runtime_url: str, runtime_id: str, runtime_token: str, room_url: str, room_id: str, room_token: str, provider: str):
    """Command to connect a Jupyter MCP Server to a room and a runtime."""

    global PROVIDER
    PROVIDER = provider

    global RUNTIME_URL
    RUNTIME_URL = runtime_url
    global RUNTIME_ID
    RUNTIME_ID = runtime_id
    global RUNTIME_TOKEN
    RUNTIME_TOKEN = runtime_token

    global ROOM_URL
    ROOM_URL = room_url
    global ROOM_ID
    ROOM_ID = room_id
    global ROOM_TOKEN
    ROOM_TOKEN = room_token

    room_runtime = RoomRuntime(
        provider=PROVIDER,
        runtime_url=RUNTIME_URL,
        runtime_id=RUNTIME_ID,
        runtime_token=RUNTIME_TOKEN,
        room_url=ROOM_URL,
        room_id=ROOM_ID,
        room_token=ROOM_TOKEN,
    )

    r = httpx.put(
        f"{jupyter_mcp_server_url}/api/connect",
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        content = room_runtime.model_dump_json()
    )
    r.raise_for_status()


@server.command("start")
@click.option("--transport", envvar="TRANSPORT", type=click.Choice(["stdio", "streamable-http"]), default="stdio", help="The transport to use for the MCP server. Defaults to 'stdio'.")
@click.option("--provider", envvar="PROVIDER", type=click.Choice(["jupyter", "datalayer"]), default="jupyter", help="The provider to use for the room and runtime. Defaults to 'jupyter'.")
@click.option("--runtime-url", envvar="RUNTIME_URL", type=click.STRING, default="http://localhost:8888", help="The runtime URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer runtime URL.") 
@click.option("--start-new-runtime", envvar="START_NEW_RUNTIME", type=click.BOOL, default=True, help="Start a new runtime or use an existing one.")
@click.option("--runtime-id", envvar="RUNTIME_ID", type=click.STRING, default=None, help="The kernel ID to use. If not provided, a new kernel should be started.")
@click.option("--runtime-token", envvar="RUNTIME_TOKEN", type=click.STRING, default=None, help="The runtime token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.")
@click.option("--room-url", envvar="ROOM_URL", type=click.STRING, default="http://localhost:8888", help="The room URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer room URL.") 
@click.option("--room-id", envvar="ROOM_ID", type=click.STRING, default="notebook.ipynb", help="The room id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path.")
@click.option("--room-token", envvar="ROOM_TOKEN", type=click.STRING, default=None, help="The room token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.")
@click.option("--port", envvar="PORT", type=click.INT, default=4040, help="The port to use for the Streamable HTTP transport. Ignored for stdio transport.")
def start_command(transport: str, start_new_runtime: bool, runtime_url: str, runtime_id: str, runtime_token: str, room_url: str, room_id: str, room_token: str, port: int, provider: str):
    """Start the Jupyter MCP server with a transport."""

    global TRANSPORT
    TRANSPORT = transport

    global PROVIDER
    PROVIDER = provider

    global RUNTIME_URL
    RUNTIME_URL = runtime_url
    global START_NEW_RUNTIME
    START_NEW_RUNTIME = start_new_runtime
    global RUNTIME_ID
    RUNTIME_ID = runtime_id
    global RUNTIME_TOKEN
    RUNTIME_TOKEN = runtime_token

    global ROOM_URL
    ROOM_URL = room_url
    global ROOM_ID
    ROOM_ID = room_id
    global ROOM_TOKEN
    ROOM_TOKEN = room_token

    if START_NEW_RUNTIME or RUNTIME_ID:
        _start_kernel()

    logger.info(f"Starting Jupyter MCP Server with transport: {transport}")

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=port)  # noqa: S104
    else:
        raise Exception("Transport should be `stdio` or `streamable-http`.")


if __name__ == "__main__":
    start()
