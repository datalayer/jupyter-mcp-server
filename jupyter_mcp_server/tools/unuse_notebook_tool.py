# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Unuse notebook tool implementation."""

import logging
from typing import Any, Optional
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager

logger = logging.getLogger(__name__)


class UnuseNotebookTool(BaseTool):
    """Tool to unuse from a notebook and release its resources.
    
    Supports both MCP_SERVER and JUPYTER_SERVER modes.
    """
    
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
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            kernel_manager: Kernel manager for JUPYTER_SERVER mode (optional kernel shutdown)
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
        
        if mode == ServerMode.JUPYTER_SERVER:
            # JUPYTER_SERVER mode: Optionally shutdown kernel before removing
            # Note: In JUPYTER_SERVER mode, kernel lifecycle is managed by kernel_manager
            # We only remove the reference in notebook_manager, the actual kernel
            # continues to run unless explicitly shutdown
            
            kernel_id = notebook_manager.get_kernel_id(notebook_name)
            if kernel_id and kernel_manager:
                try:
                    logger.info(f"Notebook '{notebook_name}' is being unused in JUPYTER_SERVER mode. Kernel {kernel_id} remains running.")
                    # Optional: Uncomment to shutdown kernel when unused
                    # await kernel_manager.shutdown_kernel(kernel_id)
                    # logger.info(f"Kernel {kernel_id} shutdown successfully")
                except Exception as e:
                    logger.warning(f"Note: Could not access kernel {kernel_id}: {e}")
            
            success = notebook_manager.remove_notebook(notebook_name)
            
        elif mode == ServerMode.MCP_SERVER:
            # MCP_SERVER mode: Use notebook_manager's remove_notebook method
            # which handles KernelClient cleanup automatically
            success = notebook_manager.remove_notebook(notebook_name)
        else:
            return f"Invalid mode: {mode}"
        
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
