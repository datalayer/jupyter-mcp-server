# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List all files and directories tool."""

from typing import Any, Optional, List, Dict
from jupyter_server_api import JupyterServerClient

from ._base import BaseTool, ServerMode
from ..config import get_config


class ListFilesTool(BaseTool):
    """List files and directories in the Jupyter server's file system.
    
    This tool recursively lists files and directories from the Jupyter server's content API,
    showing the complete file structure including notebooks, data files, scripts, and directories.
    """
    
    @property
    def name(self) -> str:
        return "list_files"
    
    @property
    def description(self) -> str:
        return "List all files and directories in the Jupyter server's file system"
    
    async def _list_files_local(
        self,
        contents_manager: Any,
        path: str = "",
        max_depth: int = 3,
        current_depth: int = 0
    ) -> List[Dict[str, Any]]:
        """List files using local contents_manager API (JUPYTER_SERVER mode)."""
        all_files = []
        
        if current_depth >= max_depth:
            return all_files
        
        try:
            # Get directory contents
            model = await contents_manager.get(path, content=True, type='directory')
            
            if 'content' not in model:
                return all_files
            
            for item in model['content']:
                item_path = item['path']
                item_type = item['type']
                
                file_info = {
                    'path': item_path,
                    'type': item_type,
                    'size': item.get('size', 0) if item_type == 'file' else 0,
                    'last_modified': item.get('last_modified', '')
                }
                all_files.append(file_info)
                
                # Recursively list subdirectories
                if item_type == 'directory':
                    subfiles = await self._list_files_local(
                        contents_manager,
                        item_path,
                        max_depth,
                        current_depth + 1
                    )
                    all_files.extend(subfiles)
                    
        except Exception:
            # Directory not accessible or doesn't exist
            pass
        
        return all_files
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[Any] = None,
        # Tool-specific parameters
        path: str = "",
        max_depth: int = 3,
        list_files_recursively_fn=None,
        **kwargs
    ) -> str:
        """List all files and directories.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            contents_manager: Direct API access for JUPYTER_SERVER mode
            path: The starting path to list from (empty string means root directory)
            max_depth: Maximum depth to recurse into subdirectories (default: 3)
            list_files_recursively_fn: Function to recursively list files (MCP_SERVER mode)
            **kwargs: Additional parameters
            
        Returns:
            Tab-separated table with columns: Path, Type, Size, Last_Modified
        """
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Local mode: use contents_manager directly
            all_files = await self._list_files_local(contents_manager, path, max_depth)
        elif mode == ServerMode.MCP_SERVER:
            # Remote mode: use HTTP client
            if list_files_recursively_fn is None:
                raise ValueError("list_files_recursively_fn is required for MCP_SERVER mode")
            
            config = get_config()
            server_client = JupyterServerClient(base_url=config.runtime_url, token=config.runtime_token)
            all_files = list_files_recursively_fn(server_client, path, 0, None, max_depth)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        if not all_files:
            return f"No files found in path '{path or 'root'}'"
        
        # Sort files by path for better readability
        all_files.sort(key=lambda x: x['path'])
        
        # Create TSV formatted output
        lines = ["Path\tType\tSize\tLast_Modified"]
        for file_info in all_files:
            lines.append(f"{file_info['path']}\t{file_info['type']}\t{file_info['size']}\t{file_info['last_modified']}")
        
        return "\n".join(lines)
