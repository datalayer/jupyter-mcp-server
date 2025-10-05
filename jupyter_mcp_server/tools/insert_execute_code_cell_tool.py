# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Insert and execute code cell tool implementation."""

from typing import Any, Optional, List, Union
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import safe_extract_outputs
from mcp.types import ImageContent


class InsertExecuteCodeCellTool(BaseTool):
    """Tool to insert and execute a code cell."""
    
    @property
    def name(self) -> str:
        return "insert_execute_code_cell"
    
    @property
    def description(self) -> str:
        return """Insert and execute a code cell in a Jupyter notebook.

Args:
    cell_index: Index of the cell to insert (0-based). Use -1 to append at end and execute.
    cell_source: Code source

Returns:
    list[Union[str, ImageContent]]: List of outputs from the executed cell"""
    
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
        cell_source: str = None,
        # Helper function passed from server.py
        ensure_kernel_alive = None,
        **kwargs
    ) -> List[Union[str, ImageContent]]:
        """Execute the insert_execute_code_cell tool.
        
        Args:
            mode: Server mode (uses notebook_manager connection)
            notebook_manager: Notebook manager instance
            cell_index: Index to insert cell (0-based, -1 to append)
            cell_source: Code source
            ensure_kernel_alive: Function to ensure kernel is alive
            **kwargs: Additional parameters
            
        Returns:
            List of outputs from the executed cell
        """
        # Ensure kernel is alive
        if ensure_kernel_alive:
            kernel = ensure_kernel_alive()
        else:
            # Fallback: get kernel from notebook_manager
            current_notebook = notebook_manager.get_current_notebook() or "default"
            kernel = notebook_manager.get_kernel(current_notebook)
            if not kernel:
                raise RuntimeError("No kernel available for execution")
        
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            total_cells = len(ydoc._ycells)
            
            actual_index = cell_index if cell_index != -1 else total_cells
                
            if actual_index < 0 or actual_index > total_cells:
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {total_cells} cells. Use -1 to append at end."
                )
            
            if actual_index == total_cells:
                notebook.add_code_cell(cell_source)
            else:
                notebook.insert_code_cell(actual_index, cell_source)
                
            notebook.execute_cell(actual_index, kernel)

            ydoc = notebook._doc
            outputs = ydoc._ycells[actual_index]["outputs"]
            return safe_extract_outputs(outputs)
