# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import logging
import os

from jupyter_kernel_client import KernelClient
from jupyter_nbmodel_client import (
    NbModelClient,
    get_jupyter_notebook_websocket_url,
)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jupyter")


NOTEBOOK_PATH = os.getenv("NOTEBOOK_PATH", "notebook.ipynb")

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8888")

TOKEN = os.getenv("TOKEN", "MY_TOKEN")


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
async def add_markdown_cell(cell_content: str) -> str:
    """Add a markdown cell in a Jupyter notebook.

    Args:
        cell_content: Markdown content

    Returns:
        str: Success message
    """
    notebook = NbModelClient(
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
    )
    await notebook.start()
    notebook.add_markdown_cell(cell_content)
    await notebook.stop()
    return "Jupyter Markdown cell added."


@mcp.tool()
async def add_execute_code_cell(cell_content: str) -> list[str]:
    """Add and execute a code cell in a Jupyter notebook.

    Args:
        cell_content: Code content

    Returns:
        list[str]: List of outputs from the executed cell
    """
    notebook = NbModelClient(
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
    )
    await notebook.start()
    cell_index = notebook.add_code_cell(cell_content)
    notebook.execute_cell(cell_index, kernel)

    ydoc = notebook._doc
    outputs = ydoc._ycells[cell_index]["outputs"]
    str_outputs = [extract_output(output) for output in outputs]

    await notebook.stop()
    
    return str_outputs


if __name__ == "__main__":
    mcp.run(transport="stdio")
