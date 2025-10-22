# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List cells tool implementation."""

from typing import Any, Optional, Literal
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.models import Notebook


class ReadNotebookTool(BaseTool):
    """Tool to read a notebook and return index, source content, type, execution count of each cell."""
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        contents_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        notebook_name: str = None,
        response_format: Literal["brief", "detailed"] = "brief",
        start_index: int = 0,
        limit: int = 20,
        **kwargs
    ) -> str:
        """Execute the read_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            notebook_name: Notebook identifier to read
            response_format: Response format (brief or detailed)
            start_index: Starting index for pagination (0-based)
            limit: Maximum number of items to return (0 means no limit)
            **kwargs: Additional parameters
            
        Returns:
            Formatted table with cell information
        """
        if notebook_name not in notebook_manager:
            return f"Notebook '{notebook_name}' is not connected. All currently connected notebooks: {list(notebook_manager.list_all_notebooks().keys())}"
        
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Local mode: read notebook directly from file system
            notebook_path = notebook_manager.get_notebook_path(notebook_name)
            
            model = await contents_manager.get(notebook_path, content=True, type='notebook')
            if 'content' not in model:
                raise ValueError(f"Could not read notebook content from {notebook_path}")
            notebook = Notebook(**model['content'])
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # Remote mode: use WebSocket connection to Y.js document
            async with notebook_manager.get_notebook_connection(notebook_name) as notebook_content:
                notebook = Notebook(**notebook_content.as_dict())
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        if start_index >= len(notebook):
            return f"Start index {start_index} is out of range. Notebook has {len(notebook)} cells."
        
        info_list = [f'Notebook {notebook_name} has {len(notebook)} cells.\n']
        info_list.append(notebook.format_output(response_format=response_format, start_index=start_index, limit=limit))

        return "\n".join(info_list)
