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
    """Extract output from a Jupyter notebook cell.
    Args:
        output: Output dictionary
    Returns:
        str: Output text
    """
    if output["output_type"] == "display_data":
        return output["data"]["text/plain"]
    elif output["output_type"] == "execute_result":
        return output["data"]["text/plain"]
    elif output["output_type"] == "stream":
        return output["text"]
    elif output["output_type"] == "error":
        return output["traceback"]
    else:
        return ""


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
async def add_execute_code_cell(cell_content: str) -> str:
    """Add and execute a code cell in a Jupyter notebook.

    Args:
        cell_content: Code content

    Returns:
        str: Cell output
    """
    notebook = NbModelClient(
        get_jupyter_notebook_websocket_url(server_url=SERVER_URL, token=TOKEN, path=NOTEBOOK_PATH)
    )
    await notebook.start()
    cell_index = notebook.add_code_cell(cell_content)
    notebook.execute_cell(cell_index, kernel)

    ydoc = notebook._doc
    outputs = ydoc._ycells[cell_index]["outputs"]
    if len(outputs) == 0:
        cell_output = ""
    else:
        cell_output = [extract_output(output) for output in outputs]

    await notebook.stop()
    return cell_output


if __name__ == "__main__":
    mcp.run(transport="stdio")
