# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Connect notebook tool implementation."""

from typing import Any, Optional, Literal
from pathlib import Path
from jupyter_server_api import JupyterServerClient, NotFoundError
from jupyter_kernel_client import KernelClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


class ConnectNotebookTool(BaseTool):
    """Tool to connect to or create a notebook file."""
    
    @property
    def name(self) -> str:
        return "connect_notebook"
    
    @property
    def description(self) -> str:
        return """Connect to a notebook file or create a new one.
    
Args:
    notebook_name: Unique identifier for the notebook
    notebook_path: Path to the notebook file, relative to the Jupyter server root (e.g. "notebook.ipynb")
    mode: "connect" to connect to existing, "create" to create new
    kernel_id: Specific kernel ID to use (optional, will create new if not provided)
    
Returns:
    str: Success message with notebook information"""
    
    async def _check_path_http(self, server_client: JupyterServerClient, notebook_path: str, mode: str) -> Optional[str]:
        """Check if path exists using HTTP API."""
        path = Path(notebook_path)
        try:
            parent_path = str(path.parent) if str(path.parent) != "." else ""
            
            if parent_path:
                dir_contents = server_client.contents.list_directory(parent_path)
            else:
                dir_contents = server_client.contents.list_directory("")
                
            if mode == "connect":
                file_exists = any(file.name == path.name for file in dir_contents)
                if not file_exists:
                    return f"'{notebook_path}' not found in jupyter server, please check the notebook already exists."
        except NotFoundError:
            parent_dir = str(path.parent) if str(path.parent) != "." else "root directory"
            return f"'{parent_dir}' not found in jupyter server, please check the directory path already exists."
        except Exception as e:
            return f"Failed to check the path '{notebook_path}': {e}"
        
        return None
    
    async def _check_path_local(self, contents_manager: Any, notebook_path: str, mode: str) -> Optional[str]:
        """Check if path exists using local contents_manager API."""
        path = Path(notebook_path)
        try:
            parent_path = str(path.parent) if str(path.parent) != "." else ""
            
            if parent_path:
                model = contents_manager.get(parent_path, content=True, type='directory')
            else:
                model = contents_manager.get("", content=True, type='directory')
            
            if mode == "connect":
                file_exists = any(item['name'] == path.name for item in model.get('content', []))
                if not file_exists:
                    return f"'{notebook_path}' not found in jupyter server, please check the notebook already exists."
        except Exception as e:
            parent_dir = str(path.parent) if str(path.parent) != "." else "root directory"
            return f"'{parent_dir}' not found in jupyter server: {e}"
        
        return None
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        notebook_name: Optional[str] = None,
        notebook_path: Optional[str] = None,
        operation_mode: Literal["connect", "create"] = "connect",
        kernel_id: Optional[str] = None,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
        **kwargs
    ) -> str:
        """Execute the connect_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            notebook_name: Unique identifier for the notebook
            notebook_path: Path to the notebook file
            operation_mode: "connect" or "create"
            kernel_id: Specific kernel ID to use (optional)
            server_url: Jupyter server URL
            token: Jupyter server token
            **kwargs: Additional parameters
            
        Returns:
            Success message with notebook information
        """
        if not notebook_name or not notebook_path:
            raise ValueError("notebook_name and notebook_path are required")
        
        if not notebook_manager:
            raise ValueError("notebook_manager is required")
        
        # Check if notebook is already connected
        if notebook_name in notebook_manager:
            return f"Notebook '{notebook_name}' is already connected. Use disconnect_notebook first if you want to reconnect."
        
        # Check server status
        if mode == ServerMode.MCP_SERVER:
            if not server_client:
                raise ValueError("server_client is required for MCP_SERVER mode")
            
            try:
                server_client.get_status()
            except Exception as e:
                return f"Failed to connect the Jupyter server: {e}"
            
            # Check path
            error = await self._check_path_http(server_client, notebook_path, operation_mode)
            if error:
                return error
            
            # Check kernel if provided
            if kernel_id:
                kernels = server_client.kernels.list_kernels()
                kernel_exists = any(kernel.id == kernel_id for kernel in kernels)
                if not kernel_exists:
                    return f"Kernel '{kernel_id}' not found in jupyter server, please check the kernel is already exists."
            
            # Create notebook if needed
            if operation_mode == "create":
                server_client.contents.create_notebook(notebook_path)
            
            # Create kernel client
            kernel = KernelClient(
                server_url=server_url,
                token=token,
                kernel_id=kernel_id
            )
            kernel.start()
            
        else:  # JUPYTER_SERVER mode
            if not contents_manager or not kernel_manager:
                raise ValueError("contents_manager and kernel_manager are required for JUPYTER_SERVER mode")
            
            # Check path using local API
            error = await self._check_path_local(contents_manager, notebook_path, operation_mode)
            if error:
                return error
            
            # Check kernel if provided
            if kernel_id:
                kernel_exists = kernel_id in kernel_manager.list_kernel_ids()
                if not kernel_exists:
                    return f"Kernel '{kernel_id}' not found in jupyter server, please check the kernel is already exists."
            
            # Create notebook if needed
            if operation_mode == "create":
                # Use contents_manager to create notebook
                contents_manager.new(path=notebook_path, type='notebook')
            
            # Start or get kernel using kernel_manager
            if kernel_id:
                # Use existing kernel
                kernel = kernel_manager.get_kernel(kernel_id)
            else:
                # Start new kernel
                kernel_id = kernel_manager.start_kernel()
                kernel = kernel_manager.get_kernel(kernel_id)
        
        # Add notebook to manager
        notebook_manager.add_notebook(
            notebook_name,
            kernel,
            server_url=server_url,
            token=token,
            path=notebook_path
        )
        notebook_manager.set_current_notebook(notebook_name)
        
        return f"Successfully {'created and ' if operation_mode == 'create' else ''}connected to notebook '{notebook_name}' at path '{notebook_path}'."
