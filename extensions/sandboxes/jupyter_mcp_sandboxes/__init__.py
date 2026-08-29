# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Sandboxes extension for Jupyter MCP Server.

This package plugs sandbox lifecycle tools and sandbox-backed execution into
Jupyter MCP Server through the reactor-powered extension mechanism.
"""

from jupyter_mcp_sandboxes.extension import SandboxesExtension

__all__ = ["SandboxesExtension"]
