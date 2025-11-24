# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Jupyter MCP Server."""

from jupyter_mcp_server.__version__ import __version__
from jupyter_mcp_server.jupyter_extension.extension import _jupyter_server_extension_points


__all__ = [
    "__version__",
    "_jupyter_server_extension_points",
]
