# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""List notebooks tool implementation."""

from typing import Any, Optional
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import format_TSV


class ListNotebooksTool(BaseTool):
    """Tool to list all managed notebooks (that have been used via use_notebook)."""
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        **kwargs
    ) -> str:
        """Execute the list_notebooks tool.
        
        This tool lists all notebooks that have been managed through the use_notebook tool.
        It does NOT perform recursive filesystem scanning.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            notebook_manager: Notebook manager instance
            **kwargs: Additional parameters (unused)
            
        Returns:
            TSV formatted table with managed notebook information
        """
        if notebook_manager is None:
            return "No notebook manager available."
        
        # Get all managed notebooks
        managed_notebooks = notebook_manager.list_all_notebooks()
        
        if not managed_notebooks:
            return "No managed notebooks. Use the use_notebook tool to manage notebooks first."
        
        # Create TSV formatted output
        headers = ["Name", "Path", "Kernel_ID", "Kernel_Status", "Activate"]
        rows = []
        
        # Sort by name for consistent output
        for name in sorted(managed_notebooks.keys()):
            info = managed_notebooks[name]
            activate_marker = "✓" if info.get("is_current") else ""
            # Get kernel_id from notebook_manager
            kernel_id = notebook_manager.get_kernel_id(name) or "-"
            rows.append([
                name,
                info.get("path", "-"),
                kernel_id,
                info.get("kernel_status", "unknown"),
                activate_marker
            ])
        
        return format_TSV(headers, rows)
