# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Jupyter to MCP Adapter Package

This package provides the adapter layer to expose MCP server tools as a Jupyter Server extension.
It supports dual-mode operation: standalone MCP server and embedded Jupyter server extension.
"""

from jupyter_mcp_server.jupyter_extension.context import ServerContext, get_server_context

__all__ = ["ServerContext", "get_server_context"]
