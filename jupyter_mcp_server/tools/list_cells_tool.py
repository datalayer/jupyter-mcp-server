# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List cells tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.config import get_config
from jupyter_nbmodel_client import NbModelClient
from jupyter_mcp_server.models import Notebook


class ListCellsTool(BaseTool):
    """Tool to list basic information of all cells."""
    
    async def _list_cells_local(self, contents_manager: Any, path: str) -> str:
        """List cells using local contents_manager (JUPYTER_SERVER mode)."""
        # Read the notebook file directly
        model = await contents_manager.get(path, content=True, type='notebook')
        
        if 'content' not in model:
            raise ValueError(f"Could not read notebook content from {path}")
        
        notebook = Notebook(**model['content'])
        return notebook.format_output(response_format="brief")
    
    def _list_cells_websocket(self, notebook_content: NbModelClient) -> str:
        """List cells using WebSocket connection (MCP_SERVER mode)."""
        notebook = Notebook(**notebook_content.as_dict())
        return notebook.format_output(response_format="brief")
    
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
            async with notebook_manager.get_current_connection() as notebook_content:
                return self._list_cells_websocket(notebook_content)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
