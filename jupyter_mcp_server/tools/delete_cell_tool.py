# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Delete cell tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


class DeleteCellTool(BaseTool):
    """Tool to delete a specific cell from a notebook."""
    
    @property
    def name(self) -> str:
        return "delete_cell"
    
    @property
    def description(self) -> str:
        return """Delete a specific cell from the Jupyter notebook.
    
Args:
    cell_index: Index of the cell to delete (0-based)
    
Returns:
    str: Success message"""
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        # Tool-specific parameters
        cell_index: int = None,
        **kwargs
    ) -> str:
        """Execute the delete_cell tool.
        
        Args:
            mode: Server mode (uses notebook_manager connection)
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to delete (0-based)
            **kwargs: Additional parameters
            
        Returns:
            Success message
        """
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc

            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )

            cell_type = ydoc._ycells[cell_index].get("cell_type", "unknown")

            # Delete the cell
            del ydoc._ycells[cell_index]

            return f"Cell {cell_index} ({cell_type}) deleted successfully."
