# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Tools package for Jupyter MCP Server.

Each tool is implemented as a separate class with an execute method
that can operate in either MCP_SERVER or JUPYTER_SERVER mode.
"""

from jupyter_mcp_server.tools.base import BaseTool, ServerMode
from jupyter_mcp_server.tools.registry import ToolRegistry, get_tool_registry, register_tool

# Import tool implementations - Notebook Management
from jupyter_mcp_server.tools.list_notebook_tool import ListNotebookTool
from jupyter_mcp_server.tools.connect_notebook_tool import ConnectNotebookTool
from jupyter_mcp_server.tools.restart_notebook_tool import RestartNotebookTool
from jupyter_mcp_server.tools.disconnect_notebook_tool import DisconnectNotebookTool
from jupyter_mcp_server.tools.switch_notebook_tool import SwitchNotebookTool

# Import tool implementations - Cell Reading
from jupyter_mcp_server.tools.read_all_cells_tool import ReadAllCellsTool
from jupyter_mcp_server.tools.list_cell_tool import ListCellTool
from jupyter_mcp_server.tools.read_cell_tool import ReadCellTool

__all__ = [
    "BaseTool",
    "ServerMode",
    "ToolRegistry",
    "get_tool_registry",
    "register_tool",
    # Notebook Management
    "ListNotebookTool",
    "ConnectNotebookTool",
    "RestartNotebookTool",
    "DisconnectNotebookTool",
    "SwitchNotebookTool",
    # Cell Reading
    "ReadAllCellsTool",
    "ListCellTool",
    "ReadCellTool",
]


