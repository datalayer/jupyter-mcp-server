# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List all files and directories tool."""

import fnmatch
from typing import Any, Optional, List, Dict
from jupyter_server_client import JupyterServerClient

from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import format_TSV


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def _list_files_mcp(
    server_client,
    current_path: str = "",
    current_depth: int = 0,
    files: Optional[List[Dict]] = None,
    max_depth: int = 1
) -> List[Dict]:
    """Recursively list all files and directories in the Jupyter server.
    
    Args:
        server_client: JupyterServerClient instance
        current_path: Current directory path
        current_depth: Current recursion depth
        files: Accumulated files list
        max_depth: Maximum recursion depth (0 means list current directory only)
    
    Returns:
        List of file/directory dictionaries with keys: path, type, size, last_modified
    """
    if files is None:
        files = []
    
    try:
        contents = server_client.contents.list_directory(current_path)
        for item in contents:
            full_path = f"{current_path}/{item.name}" if current_path else item.name
            
            # Format size
            size_str = ""
            if hasattr(item, 'size') and item.size is not None:
                size_str = format_size(item.size)
            
            # Format last modified
            last_modified = ""
            if hasattr(item, 'last_modified') and item.last_modified:
                last_modified = item.last_modified.strftime("%Y-%m-%d %H:%M:%S")
            
            # Add file/directory to list
            files.append({
                'path': full_path,
                'type': item.type,
                'size': size_str,
                'last_modified': last_modified
            })
            
            # Recursively explore directories only if we haven't reached max_depth
            # max_depth=0 means no recursion (list current directory only)
            # max_depth=1 means recurse 1 level deep, etc.
            if item.type == "directory" and current_depth < max_depth:
                _list_files_mcp(server_client, full_path, current_depth + 1, files, max_depth)
                
    except Exception as e:
        # If we can't access a directory, add an error entry
        files.append({
            'path': current_path or "root",
            'type': "error",
            'size': "",
            'last_modified': f"Error: {str(e)}"
        })
    
    return files

async def _list_files_local(
    contents_manager: Any,
    path: str = "",
    max_depth: int = 1,
    current_depth: int = 0
) -> List[Dict[str, Any]]:
    """List files using local contents_manager API (JUPYTER_SERVER mode).
    
    Args:
        contents_manager: Jupyter contents manager instance
        path: Starting directory path
        max_depth: Maximum recursion depth (0 means list current directory only)
        current_depth: Current recursion depth
        
    Returns:
        List of file/directory dictionaries
    """
    all_files = []
    
    try:
        # Get directory contents
        model = await contents_manager.get(path, content=True, type='directory')
        
        if 'content' not in model:
            return all_files
        
        for item in model['content']:
            item_path = item['path']
            item_type = item['type']
            item_size = item.get('size', 0) if item_type == 'file' else 0
            
            # Format size
            size_str = format_size(item_size) if item_size else ""
            
            # Format last modified
            last_modified = item.get('last_modified', '')
            if last_modified and hasattr(last_modified, 'strftime'):
                last_modified = last_modified.strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(last_modified, str) and 'T' in last_modified:
                # Parse ISO format timestamp
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                    last_modified = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            
            file_info = {
                'path': item_path,
                'type': item_type,
                'size': size_str,
                'last_modified': str(last_modified)
            }
            all_files.append(file_info)
            
            # Recursively list subdirectories only if we haven't reached max_depth
            # max_depth=0 means no recursion (list current directory only)
            if item_type == 'directory' and current_depth < max_depth:
                subfiles = await _list_files_local(
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

class ListFilesTool(BaseTool):
    """List files and directories in the Jupyter server's file system"""
    
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
        max_depth: int = 1,
        start_index: int = 0,
        limit: int = 25,
        pattern: Optional[str] = None,
        **kwargs
    ) -> str:
        """List all files and directories with pagination and filtering.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: JupyterServerClient for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            path: The starting path to list from (empty string means root directory)
            max_depth: Maximum depth to recurse into subdirectories (0 means list current directory only, default: 1)
            start_index: Starting index for pagination (0-based, default: 0)
            limit: Maximum number of items to return (0 means no limit, default: 25)
            pattern: Glob pattern to filter file paths (e.g., '*.py', '**/*.ipynb', default: "")
            **kwargs: Additional parameters
            
        Returns:
            Tab-separated table with columns: Path, Type, Size, Last_Modified
            Includes pagination info header.
        """
        # Get all files based on mode
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Local mode: use contents_manager directly
            all_files = await _list_files_local(contents_manager, path, max_depth)
        elif mode == ServerMode.MCP_SERVER:
            # Remote mode: use HTTP client
            config = get_config()
            server_client = JupyterServerClient(base_url=config.runtime_url, token=config.runtime_token)
            all_files = _list_files_mcp(server_client, path, 0, None, max_depth)
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
        
        if not all_files:
            return f"No files found in path '{path or 'root'}'"
        
        result = ""
        
        # Sort files by path for better readability
        all_files.sort(key=lambda x: x['path'])
        
        # Apply glob pattern filter if provided
        if pattern:
            try:
                filtered_files = [f for f in all_files if fnmatch.fnmatch(f['path'], pattern)]
                all_files = filtered_files
            except Exception:
                result += f"[WARNING] Invalid glob pattern '{pattern}', skipping pattern filter. \n"
        
        # Calculate pagination
        total_files = len(all_files)
        
        if total_files == 0:
            if pattern:
                return f"No files matching pattern '{pattern}' found in path '{path or 'root'}'"
            return f"No files found in path '{path or 'root'}'"
        if start_index >= total_files:
            result += f"[WARNING] Start index is greater than the number of files: start_index={start_index}, total_files={total_files}. Reset start_index to 0. \n"
            start_index = 0
        
        # Apply pagination
        end_index = min(start_index + limit, total_files) if limit > 0 else total_files
        paginated_files = all_files[start_index:end_index]
        
        # Prepare pagination info
        result += f"Showing {start_index}-{end_index} of {total_files} files\n\n"
        
        # Create TSV formatted output
        headers = ["Path", "Type", "Size", "Last_Modified"]
        result += format_TSV(headers, [[file['path'], file['type'], file['size'], file['last_modified']] for file in paginated_files])

        return result
