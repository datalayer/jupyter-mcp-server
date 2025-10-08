# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List cells tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import format_cell_list
from jupyter_mcp_server.config import get_config


class ListCellsTool(BaseTool):
    """Tool to list basic information of all cells."""
    
    @property
    def name(self) -> str:
        return "list_cells"
    
    @property
    def description(self) -> str:
        return """List the basic information of all cells in the notebook.
    
Returns a formatted table showing the index, type, execution count (for code cells),
and first line of each cell. This provides a quick overview of the notebook structure
and is useful for locating specific cells for operations like delete or insert.

Returns:
    str: Formatted table with cell information (Index, Type, Count, First Line)"""
    
    async def _list_cells_local(self, contents_manager: Any, path: str) -> str:
        """List cells using local contents_manager (JUPYTER_SERVER mode)."""
        # Read the notebook file directly
        model = await contents_manager.get(path, content=True, type='notebook')
        
        if 'content' not in model:
            raise ValueError(f"Could not read notebook content from {path}")
        
        notebook_content = model['content']
        cells = notebook_content.get('cells', [])
        
        # Format the cells into a table
        lines = ["Index\tType\tCount\tFirst Line"]
        lines.append("-" * 80)
        
        for idx, cell in enumerate(cells):
            cell_type = cell.get('cell_type', 'unknown')
            execution_count = cell.get('execution_count', '-') if cell_type == 'code' else '-'
            
            # Get the first line of source
            source = cell.get('source', '')
            if isinstance(source, list):
                first_line = source[0] if source else ''
            else:
                first_line = source.split('\n')[0] if source else ''
            
            # Truncate first line if too long
            if len(first_line) > 60:
                first_line = first_line[:57] + "..."
            
            lines.append(f"{idx}\t{cell_type}\t{execution_count}\t{first_line}")
        
        return "\n".join(lines)
    
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
        """Execute the list_cells tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            **kwargs: Additional parameters
            
        Returns:
            Formatted table with cell information
        """
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Local mode: read notebook directly from file system
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            from pathlib import Path
            
            context = get_server_context()
            serverapp = context.serverapp
            
            # Get current notebook path from notebook_manager if available, else use config
            notebook_path = None
            if notebook_manager:
                notebook_path = notebook_manager.get_current_notebook_path()
            if not notebook_path:
                config = get_config()
                notebook_path = config.document_id
            
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
            
            return await self._list_cells_local(contents_manager, notebook_path)
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # Remote mode: use WebSocket connection to Y.js document
            async with notebook_manager.get_current_connection() as notebook:
                ydoc = notebook._doc
                return format_cell_list(ydoc._ycells)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
