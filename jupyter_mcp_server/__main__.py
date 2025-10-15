# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Entry point for running jupyter_mcp_server as a module.

This allows the package to be run with: python -m jupyter_mcp_server
"""

from jupyter_mcp_server.CLI import server

if __name__ == "__main__":
    server()

