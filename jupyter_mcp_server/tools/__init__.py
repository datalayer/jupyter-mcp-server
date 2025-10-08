# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Tools package for Jupyter MCP Server.

Each tool is implemented as a separate class with an execute method
that can operate in either MCP_SERVER or JUPYTER_SERVER mode.
"""

from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.tools._registry import ToolRegistry, get_tool_registry, register_tool

# Import tool implementations - Notebook Management
from jupyter_mcp_server.tools.list_notebooks_tool import ListNotebooksTool
from jupyter_mcp_server.tools.restart_notebook_tool import RestartNotebookTool
from jupyter_mcp_server.tools.unuse_notebook_tool import UnuseNotebookTool
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

# Import tool implementations - Cell Reading
from jupyter_mcp_server.tools.read_cells_tool import ReadCellsTool
from jupyter_mcp_server.tools.list_cells_tool import ListCellsTool
from jupyter_mcp_server.tools.read_cell_tool import ReadCellTool

# Import tool implementations - Cell Writing
from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool
from jupyter_mcp_server.tools.insert_execute_code_cell_tool import InsertExecuteCodeCellTool
from jupyter_mcp_server.tools.overwrite_cell_source_tool import OverwriteCellSourceTool
from jupyter_mcp_server.tools.delete_cell_tool import DeleteCellTool

# Import tool implementations - Cell Execution
from jupyter_mcp_server.tools.execute_cell_simple_timeout_tool import ExecuteCellSimpleTimeoutTool
from jupyter_mcp_server.tools.execute_cell_streaming_tool import ExecuteCellStreamingTool
from jupyter_mcp_server.tools.execute_cell_with_progress_tool import ExecuteCellWithProgressTool

# Import tool implementations - Other Tools
from jupyter_mcp_server.tools.assign_kernel_to_notebook_tool import AssignKernelToNotebookTool
from jupyter_mcp_server.tools.execute_ipython_tool import ExecuteIpythonTool
from jupyter_mcp_server.tools.list_files_tool import ListFilesTool
from jupyter_mcp_server.tools.list_kernels_tool import ListKernelsTool

__all__ = [
    "BaseTool",
    "ServerMode",
    "ToolRegistry",
    "get_tool_registry",
    "register_tool",
    # Notebook Management
    "ListNotebooksTool",
    "RestartNotebookTool",
    "UnuseNotebookTool",
    "UseNotebookTool",
    # Cell Reading
    "ReadCellsTool",
    "ListCellsTool",
    "ReadCellTool",
    # Cell Writing
    "InsertCellTool",
    "InsertExecuteCodeCellTool",
    "OverwriteCellSourceTool",
    "DeleteCellTool",
    # Cell Execution
    "ExecuteCellSimpleTimeoutTool",
    "ExecuteCellStreamingTool",
    "ExecuteCellWithProgressTool",
    # Other Tools
    "AssignKernelToNotebookTool",
    "ExecuteIpythonTool",
    "ListFilesTool",
    "ListKernelsTool",
]


