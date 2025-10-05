# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Read all cells tool implementation."""

from typing import Any, Optional, List, Dict, Union
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools.base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.models import CellInfo
from mcp.types import ImageContent


class ReadAllCellsTool(BaseTool):
    """Tool to read all cells from a Jupyter notebook."""
    
    @property
    def name(self) -> str:
        return "read_all_cells"
    
    @property
    def description(self) -> str:
        return """Read all cells from the Jupyter notebook.
    
Returns:
    list[dict]: List of cell information including index, type, source,
                and outputs (for code cells)"""
    
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
    ) -> List[Dict[str, Union[str, int, List[Union[str, ImageContent]]]]]:
        """Execute the read_all_cells tool.
        
        Args:
            mode: Server mode (uses notebook_manager connection)
            notebook_manager: Notebook manager instance
            **kwargs: Additional parameters
            
        Returns:
            List of cell information dictionaries
        """
        # This tool uses notebook_manager which handles connections
        # The actual notebook content comes from NbModelClient regardless of mode
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            cells = []

            for i, cell in enumerate(ydoc._ycells):
                cells.append(CellInfo.from_cell(i, cell).model_dump(exclude_none=True))
            
            return cells
