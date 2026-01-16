# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Tools package for Jupyter MCP Server.

Each tool is implemented as a separate class with an execute method
that can operate in either MCP_SERVER or JUPYTER_SERVER mode.
"""

from jupyter_mcp_server.tools._base import BaseTool, ServerMode

# Import tool implementations - Notebook Management
from jupyter_mcp_server.tools.list_notebooks_tool import ListNotebooksTool
from jupyter_mcp_server.tools.restart_notebook_tool import RestartNotebookTool
from jupyter_mcp_server.tools.unuse_notebook_tool import UnuseNotebookTool
from jupyter_mcp_server.tools.use_notebook_tool import UseNotebookTool

# Import tool implementations - Cell Reading
from jupyter_mcp_server.tools.read_notebook_tool import ReadNotebookTool
from jupyter_mcp_server.tools.read_cell_tool import ReadCellTool

# Import tool implementations - Cell Writing
from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool
from jupyter_mcp_server.tools.overwrite_cell_source_tool import OverwriteCellSourceTool
from jupyter_mcp_server.tools.delete_cell_tool import DeleteCellTool

# Import tool implementations - Cell Execution
from jupyter_mcp_server.tools.execute_cell_tool import ExecuteCellTool

# Import tool implementations - Other Tools
from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool
from jupyter_mcp_server.tools.list_files_tool import ListFilesTool
from jupyter_mcp_server.tools.list_kernels_tool import ListKernelsTool
from jupyter_mcp_server.tools.connect_jupyter_tool import ConnectJupyterTool

# Import MCP prompt
from jupyter_mcp_server.tools.jupyter_cite_prompt import JupyterCitePrompt

__all__ = [
    "BaseTool",
    "ServerMode",
    # Notebook Management
    "ListNotebooksTool",
    "RestartNotebookTool",
    "UnuseNotebookTool",
    "UseNotebookTool",
    # Cell Reading
    "ReadNotebookTool",
    "ReadCellTool",
    # Cell Writing
    "InsertCellTool",
    "OverwriteCellSourceTool",
    "DeleteCellTool",
    # Cell Execution
    "ExecuteCellTool",
    # Other Tools
    "ExecuteCodeTool",
    "ListFilesTool",
    "ListKernelsTool",
    "ConnectJupyterTool",
    # MCP Prompt
    "JupyterCitePrompt",
]


