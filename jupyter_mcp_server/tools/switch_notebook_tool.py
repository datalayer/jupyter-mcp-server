# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Switch notebook tool implementation."""

from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools.base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager


class SwitchNotebookTool(BaseTool):
    """Tool to switch the currently active notebook."""
    
    @property
    def name(self) -> str:
        return "switch_notebook"
    
    @property
    def description(self) -> str:
        return """Switch the currently active notebook.
    
Args:
    notebook_name: Notebook identifier to switch to
    
Returns:
    str: Success message with new active notebook information"""
    
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
        """Execute the switch_notebook tool.
        
        Args:
            mode: Server mode (mode-agnostic, uses notebook_manager)
            notebook_manager: Notebook manager instance
            notebook_name: Notebook identifier to switch to
            **kwargs: Additional parameters
            
        Returns:
            Success message with new active notebook information
        """
        if notebook_name not in notebook_manager:
            available_notebooks = list(notebook_manager.list_all_notebooks().keys())
            if available_notebooks:
                return f"Notebook '{notebook_name}' is not connected. Available notebooks: {', '.join(available_notebooks)}"
            else:
                return f"Notebook '{notebook_name}' is not connected and no notebooks are available."
        
        success = notebook_manager.set_current_notebook(notebook_name)
        
        if success:
            notebooks_info = notebook_manager.list_all_notebooks()
            notebook_info = notebooks_info[notebook_name]
            
            return f"Successfully switched to notebook '{notebook_name}'. Path: '{notebook_info['path']}', Status: {notebook_info['kernel_status']}. All subsequent cell operations will use this notebook."
        else:
            return f"Failed to switch to notebook '{notebook_name}'."
