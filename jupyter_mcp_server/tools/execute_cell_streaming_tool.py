"""Execute cell with streaming progress updates tool."""

import asyncio
import time
from typing import Union
from mcp.types import ImageContent

from .base import BaseTool, ServerMode


class ExecuteCellStreamingTool(BaseTool):
    """Execute cell with streaming progress updates.
    
    To be used for long-running cells. Provides real-time progress monitoring.
    """
    
    @property
    def name(self) -> str:
        return "execute_cell_streaming"
    
    @property
    def description(self) -> str:
        return "Execute cell with streaming progress updates (for long-running cells)"
    
    async def execute(
        self,
        mode: ServerMode,
        cell_index: int,
        timeout_seconds: int = 300,
        progress_interval: int = 5,
        ensure_kernel_alive_fn=None,
        wait_for_kernel_idle_fn=None,
        extract_output_fn=None,
    ) -> list[Union[str, ImageContent]]:
        """Execute cell with streaming progress updates.
        
        Args:
            mode: Server mode (ignored, uses notebook manager)
            cell_index: Index of the cell to execute (0-based)
            timeout_seconds: Maximum time to wait for execution (default: 300s)
            progress_interval: Seconds between progress updates (default: 5s)
            ensure_kernel_alive_fn: Function to ensure kernel is alive
            wait_for_kernel_idle_fn: Function to wait for kernel idle state
            extract_output_fn: Function to extract single output
            
        Returns:
            List of outputs including progress updates
        """
        if ensure_kernel_alive_fn is None:
            raise ValueError("ensure_kernel_alive_fn is required")
        if wait_for_kernel_idle_fn is None:
            raise ValueError("wait_for_kernel_idle_fn is required")
        if extract_output_fn is None:
            raise ValueError("extract_output_fn is required")
        
        kernel = ensure_kernel_alive_fn()
        await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
        
        outputs_log = []
        
        async with self.notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(f"Cell index {cell_index} is out of range.")

            # Start execution in background
            execution_task = asyncio.create_task(
                asyncio.to_thread(notebook.execute_cell, cell_index, kernel)
            )
            
            start_time = time.time()
            last_output_count = 0
            
            # Monitor progress
            while not execution_task.done():
                elapsed = time.time() - start_time
                
                # Check timeout
                if elapsed > timeout_seconds:
                    execution_task.cancel()
                    outputs_log.append(f"[TIMEOUT at {elapsed:.1f}s: Cancelling execution]")
                    try:
                        kernel.interrupt()
                        outputs_log.append("[Sent interrupt signal to kernel]")
                    except Exception:
                        pass
                    break
                
                # Check for new outputs
                try:
                    current_outputs = ydoc._ycells[cell_index].get("outputs", [])
                    if len(current_outputs) > last_output_count:
                        new_outputs = current_outputs[last_output_count:]
                        for output in new_outputs:
                            extracted = extract_output_fn(output)
                            if extracted.strip():
                                outputs_log.append(f"[{elapsed:.1f}s] {extracted}")
                        last_output_count = len(current_outputs)
                
                except Exception as e:
                    outputs_log.append(f"[{elapsed:.1f}s] Error checking outputs: {e}")
                
                # Progress update
                if int(elapsed) % progress_interval == 0 and elapsed > 0:
                    outputs_log.append(f"[PROGRESS: {elapsed:.1f}s elapsed, {last_output_count} outputs so far]")
                
                await asyncio.sleep(1)
            
            # Get final result
            if not execution_task.cancelled():
                try:
                    await execution_task
                    final_outputs = ydoc._ycells[cell_index].get("outputs", [])
                    outputs_log.append(f"[COMPLETED in {time.time() - start_time:.1f}s]")
                    
                    # Add any final outputs not captured during monitoring
                    if len(final_outputs) > last_output_count:
                        remaining = final_outputs[last_output_count:]
                        for output in remaining:
                            extracted = extract_output_fn(output)
                            if extracted.strip():
                                outputs_log.append(extracted)
                                
                except Exception as e:
                    outputs_log.append(f"[ERROR: {e}]")
            
            return outputs_log if outputs_log else ["[No output generated]"]
