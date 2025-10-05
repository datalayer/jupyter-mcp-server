"""List all files and directories tool."""

from jupyter_server_api import JupyterServerClient

from .base import BaseTool, ServerMode
from ..config import get_config


class ListAllFilesTool(BaseTool):
    """List all files and directories in the Jupyter server's file system.
    
    This tool recursively lists files and directories from the Jupyter server's content API,
    showing the complete file structure including notebooks, data files, scripts, and directories.
    """
    
    @property
    def name(self) -> str:
        return "list_all_files"
    
    @property
    def description(self) -> str:
        return "List all files and directories in the Jupyter server's file system"
    
    async def execute(
        self,
        mode: ServerMode,
        path: str = "",
        max_depth: int = 3,
        list_files_recursively_fn=None,
    ) -> str:
        """List all files and directories.
        
        Args:
            mode: Server mode (ignored, always uses HTTP client)
            path: The starting path to list from (empty string means root directory)
            max_depth: Maximum depth to recurse into subdirectories (default: 3)
            list_files_recursively_fn: Function to recursively list files
            
        Returns:
            Tab-separated table with columns: Path, Type, Size, Last_Modified
        """
        if list_files_recursively_fn is None:
            raise ValueError("list_files_recursively_fn is required")
        
        config = get_config()
        server_client = JupyterServerClient(base_url=config.runtime_url, token=config.runtime_token)
        
        # Get all files starting from the specified path using the utility function
        all_files = list_files_recursively_fn(server_client, path, 0, None, max_depth)
        
        if not all_files:
            return f"No files found in path '{path or 'root'}'"
        
        # Sort files by path for better readability
        all_files.sort(key=lambda x: x['path'])
        
        # Create TSV formatted output
        lines = ["Path\tType\tSize\tLast_Modified"]
        for file_info in all_files:
            lines.append(f"{file_info['path']}\t{file_info['type']}\t{file_info['size']}\t{file_info['last_modified']}")
        
        return "\n".join(lines)
