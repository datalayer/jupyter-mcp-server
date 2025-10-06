# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Restart notebook tool implementation."""

import logging
from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager

logger = logging.getLogger(__name__)


class RestartNotebookTool(BaseTool):
    """Tool to restart the kernel for a specific notebook.
    
    Supports both MCP_SERVER and JUPYTER_SERVER modes.
    """
    
    @property
    def name(self) -> str:
        return "restart_notebook"
    
    @property
    def description(self) -> str:
        return """Restart the kernel for a specific notebook.
    
Args:
    notebook_name: Notebook identifier to restart
    
Returns:
    str: Success message"""
    
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
        **kwargs
    ) -> str:
        """Execute the restart_notebook tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            notebook_name: Notebook identifier to restart
            **kwargs: Additional parameters
            
        Returns:
            Success message
        """
        if notebook_name not in notebook_manager:
            return f"Notebook '{notebook_name}' is not connected."
        
        if mode == ServerMode.JUPYTER_SERVER:
            # JUPYTER_SERVER mode: Use kernel_manager to restart the kernel
            if kernel_manager is None:
                return f"Failed to restart notebook '{notebook_name}': kernel_manager is required in JUPYTER_SERVER mode."
            
            # Get kernel ID from notebook_manager
            kernel_id = notebook_manager.get_kernel_id(notebook_name)
            if not kernel_id:
                return f"Failed to restart notebook '{notebook_name}': kernel ID not found."
            
            try:
                logger.info(f"Restarting kernel {kernel_id} for notebook '{notebook_name}' in JUPYTER_SERVER mode")
                await kernel_manager.restart_kernel(kernel_id)
                return f"Notebook '{notebook_name}' kernel restarted successfully. Memory state and imported packages have been cleared."
            except Exception as e:
                logger.error(f"Failed to restart kernel {kernel_id}: {e}")
                return f"Failed to restart notebook '{notebook_name}': {e}"
        
        elif mode == ServerMode.MCP_SERVER:
            # MCP_SERVER mode: Use notebook_manager's restart_notebook method
            success = notebook_manager.restart_notebook(notebook_name)
            
            if success:
                return f"Notebook '{notebook_name}' kernel restarted successfully. Memory state and imported packages have been cleared."
            else:
                return f"Failed to restart notebook '{notebook_name}'. The kernel may not support restart operation."
        else:
            return f"Invalid mode: {mode}"
