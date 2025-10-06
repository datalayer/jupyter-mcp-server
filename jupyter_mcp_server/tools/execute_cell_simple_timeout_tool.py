# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute cell with simple timeout tool."""

import asyncio
import logging
from typing import Any, Optional, Union, List
from mcp.types import ImageContent

from ._base import BaseTool, ServerMode
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import execute_cell_local

logger = logging.getLogger(__name__)


class ExecuteCellSimpleTimeoutTool(BaseTool):
    """Execute a cell with simple timeout (no forced real-time sync).
    
    To be used for short-running cells. This won't force real-time updates
    but will work reliably. Supports both MCP_SERVER and JUPYTER_SERVER modes.
    """
    
    @property
    def name(self) -> str:
        return "execute_cell_simple_timeout"
    
    @property
    def description(self) -> str:
        return "Execute a cell with simple timeout (for short-running cells)"
    
    async def execute(
        self,
        mode: ServerMode,
        server_client=None,
        contents_manager=None,
        kernel_manager=None,
        kernel_spec_manager=None,
        notebook_manager=None,
        serverapp=None,
        # Tool-specific parameters
        cell_index: int = None,
        timeout_seconds: int = 300,
        ensure_kernel_alive_fn=None,
        wait_for_kernel_idle_fn=None,
        safe_extract_outputs_fn=None,
        **kwargs
    ) -> List[Union[str, ImageContent]]:
        """Execute a cell with simple timeout.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            serverapp: ServerApp instance for JUPYTER_SERVER mode
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager for MCP_SERVER mode
            cell_index: Index of the cell to execute (0-based)
            timeout_seconds: Maximum time to wait for execution (default: 300s)
            ensure_kernel_alive_fn: Function to ensure kernel is alive (MCP_SERVER)
            wait_for_kernel_idle_fn: Function to wait for kernel idle state (MCP_SERVER)
            safe_extract_outputs_fn: Function to safely extract outputs (MCP_SERVER)
            
        Returns:
            List of outputs from the executed cell
        """
        if mode == ServerMode.JUPYTER_SERVER:
            # JUPYTER_SERVER mode: Use centralized local execution
            if serverapp is None:
                raise ValueError("serverapp is required for JUPYTER_SERVER mode")
            if kernel_manager is None:
                raise ValueError("kernel_manager is required for JUPYTER_SERVER mode")
            
            config = get_config()
            notebook_path = config.document_id
            kernel_id = config.runtime_id
            
            logger.info(f"Executing cell {cell_index} in JUPYTER_SERVER mode (timeout: {timeout_seconds}s)")
            
            return await execute_cell_local(
                serverapp=serverapp,
                notebook_path=notebook_path,
                cell_index=cell_index,
                kernel_id=kernel_id,
                timeout=timeout_seconds,
                logger=logger
            )
        
        elif mode == ServerMode.MCP_SERVER:
            # MCP_SERVER mode: Use notebook_manager with WebSocket connection
            if ensure_kernel_alive_fn is None:
                raise ValueError("ensure_kernel_alive_fn is required for MCP_SERVER mode")
            if wait_for_kernel_idle_fn is None:
                raise ValueError("wait_for_kernel_idle_fn is required for MCP_SERVER mode")
            if safe_extract_outputs_fn is None:
                raise ValueError("safe_extract_outputs_fn is required for MCP_SERVER mode")
            if notebook_manager is None:
                raise ValueError("notebook_manager is required for MCP_SERVER mode")
            
            kernel = ensure_kernel_alive_fn()
            await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
            
            async with notebook_manager.get_current_connection() as notebook:
                ydoc = notebook._doc
                if cell_index < 0 or cell_index >= len(ydoc._ycells):
                    raise ValueError(f"Cell index {cell_index} is out of range.")

                # Simple execution with timeout
                execution_task = asyncio.create_task(
                    asyncio.to_thread(notebook.execute_cell, cell_index, kernel)
                )
                
                try:
                    await asyncio.wait_for(execution_task, timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    execution_task.cancel()
                    if kernel and hasattr(kernel, 'interrupt'):
                        kernel.interrupt()
                    return [f"[TIMEOUT ERROR: Cell execution exceeded {timeout_seconds} seconds]"]

                # Get final outputs
                outputs = ydoc._ycells[cell_index]["outputs"]
                result = safe_extract_outputs_fn(outputs)
                
                return result
        else:
            raise ValueError(f"Invalid mode: {mode}")
