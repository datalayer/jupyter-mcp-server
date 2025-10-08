# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Assign kernel to notebook tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient, NotFoundError
from jupyter_mcp_server.tools._base import BaseTool, ServerMode


class AssignKernelToNotebookTool(BaseTool):
    """Tool to assign a kernel to a notebook by creating a Jupyter session."""
    
    @property
    def name(self) -> str:
        return "assign_kernel_to_notebook"
    
    @property
    def description(self) -> str:
        return """Assign a kernel to a notebook by creating a Jupyter session.
    
This creates a Jupyter server session that connects a notebook file to a kernel,
enabling code execution in the notebook. Sessions are the mechanism Jupyter uses
to maintain the relationship between notebooks and their kernels.

Args:
    notebook_path: Path to the notebook file, relative to the Jupyter server root (e.g. "notebook.ipynb")
    kernel_id: ID of the kernel to assign to the notebook
    session_name: Optional name for the session (defaults to notebook path)
    
Returns:
    str: Success message with session information including session ID"""
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        contents_manager: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        # Tool-specific parameters
        notebook_path: str = None,
        kernel_id: str = None,
        session_name: Optional[str] = None,
        **kwargs
    ) -> str:
        """Execute the assign_kernel_to_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API access for JUPYTER_SERVER mode
            session_manager: Session manager for JUPYTER_SERVER mode
            kernel_manager: Kernel manager for validation
            notebook_path: Path to the notebook file
            kernel_id: ID of the kernel to assign
            session_name: Optional session name
            **kwargs: Additional parameters
            
        Returns:
            Success message with session information
        """
        if not notebook_path:
            return "Error: notebook_path is required"
        
        if not kernel_id:
            return "Error: kernel_id is required"
        
        # Use notebook_path as session name if not provided
        if not session_name:
            session_name = notebook_path
        
        # Verify notebook exists
        try:
            if mode == ServerMode.MCP_SERVER and server_client is not None:
                # Check notebook exists using HTTP API
                try:
                    server_client.contents.get_file(notebook_path)
                except NotFoundError:
                    return f"Error: Notebook '{notebook_path}' not found on Jupyter server"
            elif mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
                # Check notebook exists using local API
                try:
                    await contents_manager.get(notebook_path, content=False)
                except Exception as e:
                    return f"Error: Notebook '{notebook_path}' not found: {e}"
            else:
                return f"Error: Invalid mode or missing required clients: mode={mode}"
        except Exception as e:
            return f"Error checking notebook: {e}"
        
        # Verify kernel exists
        try:
            if mode == ServerMode.MCP_SERVER and server_client is not None:
                # Check kernel exists using HTTP API
                kernels = server_client.kernels.list_kernels()
                kernel_exists = any(kernel.id == kernel_id for kernel in kernels)
                if not kernel_exists:
                    return f"Error: Kernel '{kernel_id}' not found on Jupyter server"
            elif mode == ServerMode.JUPYTER_SERVER and kernel_manager is not None:
                # Check kernel exists using local API
                if kernel_id not in kernel_manager:
                    return f"Error: Kernel '{kernel_id}' not found in local kernel manager"
            else:
                return f"Error: Invalid mode or missing kernel manager: mode={mode}"
        except Exception as e:
            return f"Error checking kernel: {e}"
        
        # Create the session
        try:
            if mode == ServerMode.MCP_SERVER and server_client is not None:
                # Create session using HTTP API
                session = server_client.sessions.create_session(
                    path=notebook_path,
                    kernel={"id": kernel_id},
                    session_type="notebook",
                    name=session_name
                )
                return (
                    f"Successfully created session '{session.id}' for notebook '{notebook_path}' "
                    f"with kernel '{kernel_id}'. The notebook is now connected to the kernel."
                )
            elif mode == ServerMode.JUPYTER_SERVER and session_manager is not None:
                # Create session using local API
                # The session_manager API varies, but typically follows similar pattern
                import asyncio
                
                # Create session dict with required parameters
                session_dict = await asyncio.to_thread(
                    session_manager.create_session,
                    path=notebook_path,
                    kernel_id=kernel_id,
                    type="notebook",
                    name=session_name
                )
                
                session_id = session_dict.get("id", "unknown")
                return (
                    f"Successfully created session '{session_id}' for notebook '{notebook_path}' "
                    f"with kernel '{kernel_id}'. The notebook is now connected to the kernel."
                )
            else:
                return f"Error: Invalid mode or missing session manager: mode={mode}"
        except Exception as e:
            return f"Error creating session: {e}"
