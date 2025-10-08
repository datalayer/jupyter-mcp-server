# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List notebooks tool implementation."""

from typing import Any, Optional, List
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


class ListNotebooksTool(BaseTool):
    """Tool to list all notebooks in the Jupyter server."""
    
    @property
    def name(self) -> str:
        return "list_notebooks"
    
    @property
    def description(self) -> str:
        return """List all notebooks in the Jupyter server (including subdirectories) and show which ones are managed.
    
To interact with a notebook, it has to be "managed". If a notebook is not managed, you can connect to it using the `use_notebook` tool.

Returns:
    str: TSV formatted table with notebook information including management status"""
    
    def _list_notebooks_http(self, server_client: JupyterServerClient, path: str = "", notebooks: Optional[List[str]] = None) -> List[str]:
        """List notebooks using HTTP API (MCP_SERVER mode)."""
        if notebooks is None:
            notebooks = []
        
        try:
            contents = server_client.contents.list_directory(path)
            for item in contents:
                full_path = f"{path}/{item.name}" if path else item.name
                if item.type == "directory":
                    # Recursively search subdirectories
                    self._list_notebooks_http(server_client, full_path, notebooks)
                elif item.type == "notebook" or (item.type == "file" and item.name.endswith('.ipynb')):
                    # Add notebook to list without any prefix
                    notebooks.append(full_path)
        except Exception as e:
            # If we can't access a directory, just skip it
            pass
        
        return notebooks
    
    async def _list_notebooks_local(self, contents_manager: Any, path: str = "", notebooks: Optional[List[str]] = None) -> List[str]:
        """List notebooks using local contents_manager API (JUPYTER_SERVER mode)."""
        if notebooks is None:
            notebooks = []
        
        try:
            model = await contents_manager.get(path, content=True, type='directory')
            for item in model.get('content', []):
                full_path = f"{path}/{item['name']}" if path else item['name']
                if item['type'] == "directory":
                    # Recursively search subdirectories
                    await self._list_notebooks_local(contents_manager, full_path, notebooks)
                elif item['type'] == "notebook" or (item['type'] == "file" and item['name'].endswith('.ipynb')):
                    # Add notebook to list
                    notebooks.append(full_path)
        except Exception as e:
            # If we can't access a directory, just skip it
            pass
        
        return notebooks
    
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
        """Execute the list_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            **kwargs: Additional parameters (unused)
            
        Returns:
            TSV formatted table with notebook information
        """
        # Get all notebooks based on mode
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            all_notebooks = await self._list_notebooks_local(contents_manager)
        elif mode == ServerMode.MCP_SERVER and server_client is not None:
            all_notebooks = self._list_notebooks_http(server_client)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        # Get managed notebooks info
        managed_notebooks = notebook_manager.list_all_notebooks() if notebook_manager else {}
        
        if not all_notebooks and not managed_notebooks:
            return "No notebooks found in the Jupyter server."
        
        # Create TSV formatted output
        lines = ["Path\tManaged\tName\tStatus\tCurrent"]
        lines.append("-" * 100)
        
        # Create a set of managed notebook paths for quick lookup
        managed_paths = {info["path"] for info in managed_notebooks.values()}
        
        # Add all notebooks found in the server
        for notebook_path in sorted(all_notebooks):
            is_managed = notebook_path in managed_paths
            
            if is_managed:
                # Find the managed notebook entry
                managed_info = None
                managed_name = None
                for name, info in managed_notebooks.items():
                    if info["path"] == notebook_path:
                        managed_info = info
                        managed_name = name
                        break
                
                if managed_info:
                    current_marker = "✓" if managed_info["is_current"] else ""
                    lines.append(f"{notebook_path}\tYes\t{managed_name}\t{managed_info['kernel_status']}\t{current_marker}")
                else:
                    lines.append(f"{notebook_path}\tYes\t-\t-\t")
            else:
                lines.append(f"{notebook_path}\tNo\t-\t-\t")
        
        # Add any managed notebooks that weren't found in the server (edge case)
        for name, info in managed_notebooks.items():
            if info["path"] not in all_notebooks:
                current_marker = "✓" if info["is_current"] else ""
                lines.append(f"{info['path']}\tYes (not found)\t{name}\t{info['kernel_status']}\t{current_marker}")
        
        return "\n".join(lines)
