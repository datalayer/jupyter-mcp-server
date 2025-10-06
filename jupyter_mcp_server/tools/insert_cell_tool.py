# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Insert cell tool implementation."""

from typing import Any, Optional, Literal
from pathlib import Path
import nbformat
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_surrounding_cells_info


class InsertCellTool(BaseTool):
    """Tool to insert a cell at a specified position."""
    
    @property
    def name(self) -> str:
        return "insert_cell"
    
    @property
    def description(self) -> str:
        return """Insert a cell to specified position.

Args:
    cell_index: target index for insertion (0-based). Use -1 to append at end.
    cell_type: Type of cell to insert ("code" or "markdown")
    cell_source: Source content for the cell

Returns:
    str: Success message and the structure of its surrounding cells (up to 5 cells above and 5 cells below)"""
    
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
        cell_type: Literal["code", "markdown"] = None,
        cell_source: str = None,
        **kwargs
    ) -> str:
        """Execute the insert_cell tool.
        
        Args:
            mode: Server mode (uses notebook_manager connection)
            notebook_manager: Notebook manager instance
            cell_index: Target index for insertion (0-based, -1 to append)
            cell_type: Type of cell ("code" or "markdown")
            cell_source: Source content for the cell
            **kwargs: Additional parameters
            
        Returns:
            Success message with surrounding cells info
        """
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            total_cells = len(ydoc._ycells)
            
            actual_index = cell_index if cell_index != -1 else total_cells
                
            if actual_index < 0 or actual_index > total_cells:
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {total_cells} cells. Use -1 to append at end."
                )
            
            if cell_type == "code":
                if actual_index == total_cells:
                    notebook.add_code_cell(cell_source)
                else:
                    notebook.insert_code_cell(actual_index, cell_source)
            elif cell_type == "markdown":
                if actual_index == total_cells:
                    notebook.add_markdown_cell(cell_source)
                else:
                    notebook.insert_markdown_cell(actual_index, cell_source)
            
            # Get surrounding cells info
            new_total_cells = len(ydoc._ycells)
            surrounding_info = get_surrounding_cells_info(notebook, actual_index, new_total_cells)
            
            return f"Cell inserted successfully at index {actual_index} ({cell_type})!\n\nCurrent Surrounding Cells:\n{surrounding_info}"
