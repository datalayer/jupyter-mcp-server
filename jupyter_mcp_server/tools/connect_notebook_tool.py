# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Connect notebook tool implementation."""

from typing import Any, Optional, Literal
from pathlib import Path
from jupyter_server_api import JupyterServerClient, NotFoundError
from jupyter_kernel_client import KernelClient
from jupyter_mcp_server.tools.base import BaseTool, ServerMode
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
    
    async def _check_path_http(
        self, 
        server_client: JupyterServerClient, 
        notebook_path: str, 
        mode: str
    ) -> tuple[bool, Optional[str]]:
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
                    return False, f"'{notebook_path}' not found in jupyter server, please check the notebook already exists."
            
            return True, None
        except NotFoundError:
            parent_dir = str(path.parent) if str(path.parent) != "." else "root directory"
            return False, f"'{parent_dir}' not found in jupyter server, please check the directory path already exists."
        except Exception as e:
            return False, f"Failed to check the path '{notebook_path}': {e}"
    
    async def _check_path_local(
        self,
        contents_manager: Any,
        notebook_path: str,
        mode: str
    ) -> tuple[bool, Optional[str]]:
        """Check if path exists using local contents_manager API."""
        path = Path(notebook_path)
        try:
            parent_path = str(path.parent) if str(path.parent) != "." else ""
            
            # Get directory contents using local API
            model = await contents_manager.get(parent_path, content=True, type='directory')
            
            if mode == "connect":
                file_exists = any(item['name'] == path.name for item in model.get('content', []))
                if not file_exists:
                    return False, f"'{notebook_path}' not found in jupyter server, please check the notebook already exists."
            
            return True, None
        except Exception as e:
            parent_dir = str(path.parent) if str(path.parent) != "." else "root directory"
            return False, f"'{parent_dir}' not found in jupyter server: {e}"
    
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
        notebook_name: str = None,
        notebook_path: str = None,
        connect_mode: Literal["connect", "create"] = "connect",
        kernel_id: Optional[str] = None,
        runtime_url: Optional[str] = None,
        runtime_token: Optional[str] = None,
        **kwargs
    ) -> str:
        """Execute the connect_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            kernel_manager: Direct kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            notebook_name: Unique identifier for the notebook
            notebook_path: Path to the notebook file
            connect_mode: "connect" or "create"
            kernel_id: Optional specific kernel ID
            runtime_url: Runtime URL for HTTP mode
            runtime_token: Runtime token for HTTP mode
            **kwargs: Additional parameters
            
        Returns:
            Success message with notebook information
        """
        if notebook_name in notebook_manager:
            return f"Notebook '{notebook_name}' is already connected. Use disconnect_notebook first if you want to reconnect."
        
        # Check server connectivity (HTTP mode only)
        if mode == ServerMode.MCP_SERVER and server_client is not None:
            try:
                server_client.get_status()
            except Exception as e:
                return f"Failed to connect the Jupyter server: {e}"
        
        # Check the path exists
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            path_ok, error_msg = await self._check_path_local(contents_manager, notebook_path, connect_mode)
        elif mode == ServerMode.MCP_SERVER and server_client is not None:
            path_ok, error_msg = await self._check_path_http(server_client, notebook_path, connect_mode)
        else:
            return f"Invalid mode or missing required clients: mode={mode}"
        
        if not path_ok:
            return error_msg
        
        # Check kernel if kernel_id provided (HTTP mode only for now)
        if kernel_id and mode == ServerMode.MCP_SERVER and server_client is not None:
            kernels = server_client.kernels.list_kernels()
            kernel_exists = any(kernel.id == kernel_id for kernel in kernels)
            if not kernel_exists:
                return f"Kernel '{kernel_id}' not found in jupyter server, please check the kernel already exists."
        
        # Create notebook if needed
        if connect_mode == "create":
            if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
                # Use local API to create notebook
                await contents_manager.new(model={'type': 'notebook'}, path=notebook_path)
            elif mode == ServerMode.MCP_SERVER and server_client is not None:
                server_client.contents.create_notebook(notebook_path)
        
        # Create kernel client (currently always uses HTTP approach)
        # TODO: In JUPYTER_SERVER mode, could use kernel_manager.start_kernel() directly
        kernel = KernelClient(
            server_url=runtime_url,
            token=runtime_token,
            kernel_id=kernel_id
        )
        kernel.start()
        
        # Add notebook to manager
        notebook_manager.add_notebook(
            notebook_name,
            kernel,
            server_url=runtime_url,
            token=runtime_token,
            path=notebook_path
        )
        notebook_manager.set_current_notebook(notebook_name)
        
        return f"Successfully {'created and ' if connect_mode == 'create' else ''}connected to notebook '{notebook_name}' at path '{notebook_path}'."
