# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Read all cells tool implementation."""

from typing import Any, Optional, List, Dict, Union
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.models import CellInfo
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import get_current_notebook_context
from mcp.types import ImageContent


class ReadCellsTool(BaseTool):
    """Tool to read cells from a Jupyter notebook."""
    
    @property
    def name(self) -> str:
        return "read_cells"
    
    @property
    def description(self) -> str:
        return """Read cells from the Jupyter notebook.
    
Returns:
    list[dict]: List of cell information including index, type, source,
                and outputs (for code cells)"""
    
    async def _read_cells_local(self, contents_manager: Any, path: str) -> List[Dict[str, Any]]:
        """Read cells using local contents_manager (JUPYTER_SERVER mode)."""
        # Read the notebook file directly
        model = await contents_manager.get(path, content=True, type='notebook')
        
        if 'content' not in model:
            raise ValueError(f"Could not read notebook content from {path}")
        
        notebook_content = model['content']
        cells = notebook_content.get('cells', [])
        
        # Convert cells to the expected format using CellInfo for consistency
        result = []
        for idx, cell in enumerate(cells):
            # Use CellInfo.from_cell to ensure consistent structure and output processing
            cell_info = CellInfo.from_cell(cell_index=idx, cell=cell)
            result.append(cell_info.model_dump(exclude_none=True))
        
        return result
    
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
        """Execute the read_cells tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance for MCP_SERVER mode
            **kwargs: Additional parameters
            
        Returns:
            List of cell information dictionaries
        """
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Local mode: read notebook directly from file system
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            from pathlib import Path
            
            context = get_server_context()
            serverapp = context.serverapp
            
            notebook_path, _ = get_current_notebook_context(notebook_manager)
            
            # contents_manager expects path relative to serverapp.root_dir
            # If we have an absolute path, convert it to relative
            if serverapp and Path(notebook_path).is_absolute():
                root_dir = Path(serverapp.root_dir)
                abs_path = Path(notebook_path)
                try:
                    notebook_path = str(abs_path.relative_to(root_dir))
                except ValueError:
                    # Path is not under root_dir, use as-is
                    pass
            
            return await self._read_cells_local(contents_manager, notebook_path)
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # Remote mode: use WebSocket connection to Y.js document
            async with notebook_manager.get_current_connection() as notebook:
                ydoc = notebook._doc
                cells = []

                for i, cell in enumerate(ydoc._ycells):
                    cells.append(CellInfo.from_cell(i, cell).model_dump(exclude_none=True))
                
                return cells
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
