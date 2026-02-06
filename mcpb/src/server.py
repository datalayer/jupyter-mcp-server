#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Jupyter MCP Server - MCPB entry point for Claude Desktop.

This is a thin wrapper that launches the Jupyter MCP Server
in stdio transport mode for use with Claude Desktop and other
MCP-compatible applications.

Configuration is provided via environment variables set by
the host application from the manifest's user_config:
  - JUPYTER_URL: URL of the Jupyter server
  - JUPYTER_TOKEN: Authentication token for the Jupyter server
"""

from jupyter_mcp_server.CLI import server

if __name__ == "__main__":
    server()
