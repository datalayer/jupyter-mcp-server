"""Execute cell with simple timeout tool."""

import asyncio
from typing import Union
from mcp.types import ImageContent

from ._base import BaseTool, ServerMode


class ExecuteCellSimpleTimeoutTool(BaseTool):
    """Execute a cell with simple timeout (no forced real-time sync).
    
    To be used for short-running cells. This won't force real-time updates
    but will work reliably.
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
        cell_index: int,
        timeout_seconds: int = 300,
        ensure_kernel_alive_fn=None,
        wait_for_kernel_idle_fn=None,
        safe_extract_outputs_fn=None,
    ) -> list[Union[str, ImageContent]]:
        """Execute a cell with simple timeout.
        
        Args:
            mode: Server mode (ignored, uses notebook manager)
            cell_index: Index of the cell to execute (0-based)
            timeout_seconds: Maximum time to wait for execution (default: 300s)
            ensure_kernel_alive_fn: Function to ensure kernel is alive
            wait_for_kernel_idle_fn: Function to wait for kernel idle state
            safe_extract_outputs_fn: Function to safely extract outputs
            
        Returns:
            List of outputs from the executed cell
        """
        if ensure_kernel_alive_fn is None:
            raise ValueError("ensure_kernel_alive_fn is required")
        if wait_for_kernel_idle_fn is None:
            raise ValueError("wait_for_kernel_idle_fn is required")
        if safe_extract_outputs_fn is None:
            raise ValueError("safe_extract_outputs_fn is required")
        
        kernel = ensure_kernel_alive_fn()
        await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
        
        async with self.notebook_manager.get_current_connection() as notebook:
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
