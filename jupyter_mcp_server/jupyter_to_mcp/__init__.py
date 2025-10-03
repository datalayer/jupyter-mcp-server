# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Jupyter-to-MCP Adapter Extension

This extension provides HTTP REST API endpoints that expose MCP tools
through standard HTTP requests, acting as an adapter between HTTP clients
and the MCP protocol.
"""

from .extension import JupyterToMCPExtension, _load_jupyter_server_extension

__all__ = ["JupyterToMCPExtension", "_load_jupyter_server_extension"]


def _jupyter_server_extension_points():
    """
    Returns a list of dictionaries with metadata describing
    where to find the `_load_jupyter_server_extension` function.
    """
    return [
        {
            "module": "jupyter_mcp_server.jupyter_to_mcp",
            "app": JupyterToMCPExtension
        }
    ]
