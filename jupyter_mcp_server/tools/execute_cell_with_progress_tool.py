"""Execute cell with progress monitoring tool."""

import asyncio
import logging
from typing import Union
from mcp.types import ImageContent

from .base import BaseTool, ServerMode

logger = logging.getLogger(__name__)


class ExecuteCellWithProgressTool(BaseTool):
    """Execute a specific cell with timeout and progress monitoring.
    
    Uses forced synchronization to ensure real-time progress updates.
    """
    
    @property
    def name(self) -> str:
        return "execute_cell_with_progress"
    
    @property
    def description(self) -> str:
        return "Execute cell with timeout and progress monitoring"
    
    async def execute(
        self,
        mode: ServerMode,
        cell_index: int,
        timeout_seconds: int = 300,
        ensure_kernel_alive_fn=None,
        wait_for_kernel_idle_fn=None,
        safe_extract_outputs_fn=None,
        execute_cell_with_forced_sync_fn=None,
    ) -> list[Union[str, ImageContent]]:
        """Execute a specific cell with timeout and progress monitoring.
        
        Args:
            mode: Server mode (ignored, uses notebook manager)
            cell_index: Index of the cell to execute (0-based)
            timeout_seconds: Maximum time to wait for execution (default: 300s)
            ensure_kernel_alive_fn: Function to ensure kernel is alive
            wait_for_kernel_idle_fn: Function to wait for kernel idle state
            safe_extract_outputs_fn: Function to safely extract outputs
            execute_cell_with_forced_sync_fn: Function to execute cell with forced sync
            
        Returns:
            List of outputs from the executed cell
        """
        if ensure_kernel_alive_fn is None:
            raise ValueError("ensure_kernel_alive_fn is required")
        if wait_for_kernel_idle_fn is None:
            raise ValueError("wait_for_kernel_idle_fn is required")
        if safe_extract_outputs_fn is None:
            raise ValueError("safe_extract_outputs_fn is required")
        if execute_cell_with_forced_sync_fn is None:
            raise ValueError("execute_cell_with_forced_sync_fn is required")
        
        kernel = ensure_kernel_alive_fn()
        await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
        
        async with self.notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc

            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )

            logger.info(f"Starting execution of cell {cell_index} with {timeout_seconds}s timeout")
            
            try:
                # Use the corrected timeout function
                await execute_cell_with_forced_sync_fn(notebook, cell_index, kernel, timeout_seconds)

                # Get final outputs
                ydoc = notebook._doc
                outputs = ydoc._ycells[cell_index]["outputs"]
                result = safe_extract_outputs_fn(outputs)
                
                logger.info(f"Cell {cell_index} completed successfully with {len(result)} outputs")
                return result
                
            except asyncio.TimeoutError as e:
                logger.error(f"Cell {cell_index} execution timed out: {e}")
                try:
                    if kernel and hasattr(kernel, 'interrupt'):
                        kernel.interrupt()
                        logger.info("Sent interrupt signal to kernel")
                except Exception as interrupt_err:
                    logger.error(f"Failed to interrupt kernel: {interrupt_err}")
                
                # Return partial outputs if available
                try:
                    outputs = ydoc._ycells[cell_index].get("outputs", [])
                    partial_outputs = safe_extract_outputs_fn(outputs)
                    partial_outputs.append(f"[TIMEOUT ERROR: Execution exceeded {timeout_seconds} seconds]")
                    return partial_outputs
                except Exception:
                    pass
                
                return [f"[TIMEOUT ERROR: Cell execution exceeded {timeout_seconds} seconds and was interrupted]"]
                
            except Exception as e:
                logger.error(f"Error executing cell {cell_index}: {e}")
                raise
