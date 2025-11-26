# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Read cell tool implementation."""

from typing import Any, Optional
from jupyter_server_client import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.models import Notebook
from jupyter_mcp_server.config import get_config
from mcp.types import ImageContent


class ReadCellTool(BaseTool):
    """Tool to read a specific cell from a notebook."""
    
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
        include_outputs: bool = True,
        **kwargs
    ) -> list[str | ImageContent]:
        """Execute the read_cell tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            cell_index: Index of the cell to read (0-based)
            include_outputs: Include outputs in the response (only for code cells)
            **kwargs: Additional parameters
            
        Returns:
            Cell information dictionary
        """
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Local mode: read notebook directly from file system
            notebook_path = notebook_manager.get_current_notebook_path()
            
            model = await contents_manager.get(notebook_path, content=True, type='notebook')
            if 'content' not in model:
                raise ValueError(f"Could not read notebook content from {notebook_path}")
            notebook = Notebook(**model['content'])
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # Remote mode: use WebSocket connection to Y.js document
            async with notebook_manager.get_current_connection() as notebook_content:
                notebook = Notebook(**notebook_content.as_dict())
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        if cell_index >= len(notebook):
            return f"Cell index {cell_index} is out of range. Notebook has {len(notebook)} cells."
        cell = notebook[cell_index]
        info_list = []
        # add cell metadata
        info_list.append(f"=====Cell {cell_index} | type: {cell.cell_type} | execution count: {cell.execution_count if cell.execution_count else 'N/A'}=====")
        # add cell source
        info_list.append(cell.get_source('readable'))
        # add cell outputs for code cells
        if cell.cell_type == "code" and include_outputs:
            info_list.extend(cell.get_outputs('readable'))
        
        return info_list
