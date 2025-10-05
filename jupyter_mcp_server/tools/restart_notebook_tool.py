# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Restart notebook tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


class RestartNotebookTool(BaseTool):
    """Tool to restart the kernel for a specific notebook."""
    
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
            mode: Server mode (mode-agnostic, uses notebook_manager)
            notebook_manager: Notebook manager instance
            notebook_name: Notebook identifier to restart
            **kwargs: Additional parameters
            
        Returns:
            Success message
        """
        if notebook_name not in notebook_manager:
            return f"Notebook '{notebook_name}' is not connected."
        
        success = notebook_manager.restart_notebook(notebook_name)
        
        if success:
            return f"Notebook '{notebook_name}' kernel restarted successfully. Memory state and imported packages have been cleared."
        else:
            return f"Failed to restart notebook '{notebook_name}'. The kernel may not support restart operation."
