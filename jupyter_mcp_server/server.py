# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import logging
import os
from typing import Union

from jupyter_kernel_client import KernelClient
from jupyter_nbmodel_client import (
    NbModelClient,
    get_jupyter_notebook_websocket_url,
)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jupyter")


NOTEBOOK_PATH: str = os.getenv("NOTEBOOK_PATH", "notebook.ipynb")

SERVER_URL: str = os.getenv("SERVER_URL", "http://localhost:8888")

TOKEN: str = os.getenv("TOKEN", "MY_TOKEN")


logger = logging.getLogger(__name__)


kernel = KernelClient(server_url=SERVER_URL, token=TOKEN)
kernel.start()


def extract_output(output: dict) -> str:
    """
    Extracts readable output from a Jupyter cell output dictionary.

    Args:
        output (dict): The output dictionary from a Jupyter cell.

    Returns:
        str: A string representation of the output.
    """
    output_type = output.get("output_type")
    if output_type == "stream":
        return output.get("text", "")
    elif output_type in ["display_data", "execute_result"]:
        data = output.get("data", {})
        if "text/plain" in data:
            return data["text/plain"]
        elif "text/html" in data:
            return "[HTML Output]"
        elif "image/png" in data:
            return "[Image Output (PNG)]"
        else:
            return f"[{output_type} Data: keys={list(data.keys())}]"
    elif output_type == "error":
        return output["traceback"]
    else:
        return f"[Unknown output type: {output_type}]"


@mcp.tool()
async def add_markdown_cell(cell_source: str) -> str:
    """Add a markdown cell in a Jupyter notebook.

    Args:
        cell_source: Markdown source

    Returns:
        str: Success message
    """
    notebook = NbModelClient(
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
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
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
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
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
    )
    await notebook.start()
    notebook.set_cell_source(cell_index, cell_source)
    await notebook.stop()
    return f"Cell {cell_index} overwritten successfully - use execute_cell to execute it if code"


@mcp.tool()
async def add_execute_code_cell(cell_source: str) -> list[str]:
    """Add and execute a code cell in a Jupyter notebook.

    Args:
        cell_source: Code source

    Returns:
        list[str]: List of outputs from the executed cell
    """
    notebook = NbModelClient(
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
    )
    await notebook.start()
    cell_index = notebook.add_code_cell(cell_source)
    notebook.execute_cell(cell_index, kernel)

    ydoc = notebook._doc
    outputs = ydoc._ycells[cell_index]["outputs"]
    str_outputs = [extract_output(output) for output in outputs]

    await notebook.stop()

    return str_outputs


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
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
    )
    await notebook.start()
    notebook.insert_code_cell(cell_index, cell_source)
    notebook.execute_cell(cell_index, kernel)

    ydoc = notebook._doc
    outputs = ydoc._ycells[cell_index]["outputs"]
    str_outputs = [extract_output(output) for output in outputs]

    await notebook.stop()

    return str_outputs


# TODO: Add clear_outputs(cell_index: int) function
# But we need to expose reset_cell in NbModelClient:
# https://github.com/datalayer/jupyter-nbmodel-client/blob/main/jupyter_nbmodel_client/model.py#L297-L301


@mcp.tool()
async def execute_cell(cell_index: int) -> list[str]:
    """Execute a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to execute (0-based)
    Returns:
        list[str]: List of outputs from the executed cell
    """
    notebook = NbModelClient(
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
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
    str_outputs = [extract_output(output) for output in outputs]

    await notebook.stop()
    return str_outputs


@mcp.tool()
async def read_all_cells() -> list[dict[str, Union[str, int, list[str]]]]:
    """Read all cells from the Jupyter notebook.
    Returns:
        list[dict]: List of cell information including index, type, source,
                    and outputs (for code cells)
    """
    notebook = NbModelClient(
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
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
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
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
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
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
        "notebook_path": NOTEBOOK_PATH,
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
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
