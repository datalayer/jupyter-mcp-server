# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Use notebook tool implementation."""

import logging
from typing import Any, Optional, Literal
from pathlib import Path
from jupyter_server_api import JupyterServerClient, NotFoundError
from jupyter_kernel_client import KernelClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager

logger = logging.getLogger(__name__)


class UseNotebookTool(BaseTool):
    """Tool to use (connect to or create) a notebook file."""
    
    @property
    def name(self) -> str:
        return "use_notebook"
    
    @property
    def description(self) -> str:
        return """Use a notebook file (connect to existing, create new, or switch to already-connected notebook).
    
Args:
    notebook_name: Unique identifier for the notebook
    notebook_path: Path to the notebook file, relative to the Jupyter server root (e.g. "notebook.ipynb").
                  Optional - if not provided, switches to an already-connected notebook with the given name.
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
        session_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        # Tool-specific parameters
        notebook_name: str = None,
        notebook_path: Optional[str] = None,
        use_mode: Literal["connect", "create"] = "connect",
        kernel_id: Optional[str] = None,
        runtime_url: Optional[str] = None,
        runtime_token: Optional[str] = None,
        **kwargs
    ) -> str:
        """Execute the use_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            kernel_manager: Direct kernel manager for JUPYTER_SERVER mode
            session_manager: Session manager for creating kernel-notebook associations
            notebook_manager: Notebook manager instance
            notebook_name: Unique identifier for the notebook
            notebook_path: Path to the notebook file (optional, if not provided switches to existing notebook)
            use_mode: "connect" or "create"
            kernel_id: Optional specific kernel ID
            runtime_url: Runtime URL for HTTP mode
            runtime_token: Runtime token for HTTP mode
            **kwargs: Additional parameters
            
        Returns:
            Success message with notebook information
        """
        # If no notebook_path provided, switch to already-connected notebook
        if notebook_path is None:
            if notebook_name not in notebook_manager:
                return f"Notebook '{notebook_name}' is not connected. Please provide a notebook_path to connect to it first."
            
            # Switch to the existing notebook
            notebook_manager.set_current_notebook(notebook_name)
            return f"Successfully switched to notebook '{notebook_name}'."
        
        # Rest of the logic for connecting/creating new notebooks
        if notebook_name in notebook_manager:
            return f"Notebook '{notebook_name}' is already using. Use unuse_notebook first if you want to reconnect."
        
        # Check server connectivity (HTTP mode only)
        if mode == ServerMode.MCP_SERVER and server_client is not None:
            try:
                server_client.get_status()
            except Exception as e:
                return f"Failed to connect the Jupyter server: {e}"
        
        # Check the path exists
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            path_ok, error_msg = await self._check_path_local(contents_manager, notebook_path, use_mode)
        elif mode == ServerMode.MCP_SERVER and server_client is not None:
            path_ok, error_msg = await self._check_path_http(server_client, notebook_path, use_mode)
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
        if use_mode == "create":
            if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
                # Use local API to create notebook
                await contents_manager.new(model={'type': 'notebook'}, path=notebook_path)
            elif mode == ServerMode.MCP_SERVER and server_client is not None:
                server_client.contents.create_notebook(notebook_path)
        
        # Create/connect to kernel based on mode
        if mode == ServerMode.JUPYTER_SERVER and kernel_manager is not None:
            # JUPYTER_SERVER mode: Use local kernel manager API directly
            if kernel_id:
                # Connect to existing kernel - verify it exists
                if kernel_id not in kernel_manager:
                    return f"Kernel '{kernel_id}' not found in local kernel manager."
                kernel_info = {"id": kernel_id}
            else:
                # Start a new kernel using local API
                kernel_id = await kernel_manager.start_kernel()
                logger.info(f"Started kernel '{kernel_id}', waiting for it to be ready...")
                
                # CRITICAL: Wait for the kernel to actually start and be ready
                # The start_kernel() call returns immediately, but kernel takes time to start
                import asyncio
                max_wait_time = 30  # seconds
                wait_interval = 0.5  # seconds
                elapsed = 0
                kernel_ready = False
                
                while elapsed < max_wait_time:
                    try:
                        # Get kernel model to check its state
                        kernel_model = kernel_manager.get_kernel(kernel_id)
                        if kernel_model is not None:
                            # Kernel exists, check if it's ready
                            # In Jupyter, we can try to get connection info which indicates readiness
                            try:
                                kernel_manager.get_connection_info(kernel_id)
                                kernel_ready = True
                                logger.info(f"Kernel '{kernel_id}' is ready (took {elapsed:.1f}s)")
                                break
                            except:
                                # Connection info not available yet, kernel still starting
                                pass
                    except Exception as e:
                        logger.debug(f"Waiting for kernel to start: {e}")
                    
                    await asyncio.sleep(wait_interval)
                    elapsed += wait_interval
                
                if not kernel_ready:
                    logger.warning(f"Kernel '{kernel_id}' may not be fully ready after {max_wait_time}s wait")
                
                kernel_info = {"id": kernel_id}
            
            # Create a Jupyter session to associate the kernel with the notebook
            # This is CRITICAL for JupyterLab to recognize the kernel-notebook connection
            if session_manager is not None:
                try:
                    # create_session is an async method, so we await it directly
                    session_dict = await session_manager.create_session(
                        path=notebook_path,
                        kernel_id=kernel_id,
                        type="notebook",
                        name=notebook_path
                    )
                    logger.info(f"Created Jupyter session '{session_dict.get('id')}' for notebook '{notebook_path}' with kernel '{kernel_id}'")
                except Exception as e:
                    logger.warning(f"Failed to create Jupyter session: {e}. Notebook may not be properly connected in JupyterLab UI.")
            else:
                logger.warning("No session_manager available. Notebook may not be properly connected in JupyterLab UI.")
            
            # For JUPYTER_SERVER mode, store kernel info (not KernelClient object)
            # The actual kernel is managed by kernel_manager
            notebook_manager.add_notebook(
                notebook_name,
                kernel_info,  # Store kernel metadata, not client object
                server_url="local",  # Indicate local mode
                token=None,
                path=notebook_path
            )
        elif mode == ServerMode.MCP_SERVER and runtime_url:
            # MCP_SERVER mode: Use HTTP-based kernel client
            kernel = KernelClient(
                server_url=runtime_url,
                token=runtime_token,
                kernel_id=kernel_id
            )
            kernel.start()
            
            # Add notebook to manager with HTTP client
            notebook_manager.add_notebook(
                notebook_name,
                kernel,
                server_url=runtime_url,
                token=runtime_token,
                path=notebook_path
            )
        else:
            return f"Invalid configuration: mode={mode}, runtime_url={runtime_url}, kernel_manager={kernel_manager is not None}"
        
        notebook_manager.set_current_notebook(notebook_name)
        
        # Return message based on mode
        if use_mode == "create":
            return f"Successfully created and using notebook '{notebook_name}' at path '{notebook_path}' in {mode.value} mode."
        else:
            return f"Successfully using notebook '{notebook_name}' at path '{notebook_path}' in {mode.value} mode."
