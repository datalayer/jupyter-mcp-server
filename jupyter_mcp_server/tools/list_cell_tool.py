# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List cell tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import format_cell_list


class ListCellTool(BaseTool):
    """Tool to list basic information of all cells."""
    
    @property
    def name(self) -> str:
        return "list_cell"
    
    @property
    def description(self) -> str:
        return """List the basic information of all cells in the notebook.
    
Returns a formatted table showing the index, type, execution count (for code cells),
and first line of each cell. This provides a quick overview of the notebook structure
and is useful for locating specific cells for operations like delete or insert.

Returns:
    str: Formatted table with cell information (Index, Type, Count, First Line)"""
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        **kwargs
    ) -> str:
        """Execute the list_cell tool.
        
        Args:
            mode: Server mode (uses notebook_manager connection)
            notebook_manager: Notebook manager instance
            **kwargs: Additional parameters
            
        Returns:
            Formatted table with cell information
        """
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            return format_cell_list(ydoc._ycells)
