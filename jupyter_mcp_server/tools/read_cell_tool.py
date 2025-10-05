# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Read cell tool implementation."""

from typing import Any, Optional, Dict, Union, List
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools.base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.models import CellInfo
from mcp.types import ImageContent


class ReadCellTool(BaseTool):
    """Tool to read a specific cell from a notebook."""
    
    @property
    def name(self) -> str:
        return "read_cell"
    
    @property
    def description(self) -> str:
        return """Read a specific cell from the Jupyter notebook.
    
Args:
    cell_index: Index of the cell to read (0-based)
    
Returns:
    dict: Cell information including index, type, source, and outputs (for code cells)"""
    
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
    ) -> Dict[str, Union[str, int, List[Union[str, ImageContent]]]]:
        """Execute the read_cell tool.
        
        Args:
            mode: Server mode (uses notebook_manager connection)
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to read (0-based)
            **kwargs: Additional parameters
            
        Returns:
            Cell information dictionary
        """
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc

            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )

            cell = ydoc._ycells[cell_index]
            return CellInfo.from_cell(cell_index=cell_index, cell=cell).model_dump(exclude_none=True)
