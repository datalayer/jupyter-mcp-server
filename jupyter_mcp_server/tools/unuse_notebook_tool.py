# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Unuse notebook tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


class UnuseNotebookTool(BaseTool):
    """Tool to unuse from a notebook and release its resources."""
    
    @property
    def name(self) -> str:
        return "unuse_notebook"
    
    @property
    def description(self) -> str:
        return """Unuse a specific notebook and release its resources.
    
Args:
    notebook_name: Notebook identifier to unuse
    
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
        """Execute the unuse_notebook tool.
        
        Args:
            mode: Server mode (mode-agnostic, uses notebook_manager)
            notebook_manager: Notebook manager instance
            notebook_name: Notebook identifier to disconnect
            **kwargs: Additional parameters
            
        Returns:
            Success message
        """
        if notebook_name not in notebook_manager:
            return f"Notebook '{notebook_name}' is not connected."
        
        # Get info about which notebook was current
        current_notebook = notebook_manager.get_current_notebook()
        was_current = current_notebook == notebook_name
        
        success = notebook_manager.remove_notebook(notebook_name)
        
        if success:
            message = f"Notebook '{notebook_name}' unused successfully."
            
            if was_current:
                new_current = notebook_manager.get_current_notebook()
                if new_current:
                    message += f" Current notebook switched to '{new_current}'."
                else:
                    message += " No notebooks remaining."
            
            return message
        else:
            return f"Notebook '{notebook_name}' was not found."
