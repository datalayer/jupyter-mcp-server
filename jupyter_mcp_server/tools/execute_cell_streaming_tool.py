# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute cell with streaming progress updates tool."""

import asyncio
import time
import logging
from typing import Union, List
from mcp.types import ImageContent

from ._base import BaseTool, ServerMode
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import execute_cell_local

logger = logging.getLogger(__name__)


class ExecuteCellStreamingTool(BaseTool):
    """Execute cell with streaming progress updates.
    
    To be used for long-running cells. Provides real-time progress monitoring
    in MCP_SERVER mode via WebSocket. In JUPYTER_SERVER mode, uses standard execution.
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
        server_client=None,
        contents_manager=None,
        kernel_manager=None,
        kernel_spec_manager=None,
        notebook_manager=None,
        serverapp=None,
        # Tool-specific parameters
        cell_index: int = None,
        timeout_seconds: int = 300,
        progress_interval: int = 5,
        ensure_kernel_alive_fn=None,
        wait_for_kernel_idle_fn=None,
        extract_output_fn=None,
        **kwargs
    ) -> List[Union[str, ImageContent]]:
        """Execute cell with streaming progress updates.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            serverapp: ServerApp instance for JUPYTER_SERVER mode
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager for MCP_SERVER mode
            cell_index: Index of the cell to execute (0-based)
            timeout_seconds: Maximum time to wait for execution (default: 300s)
            progress_interval: Seconds between progress updates (default: 5s, MCP_SERVER only)
            ensure_kernel_alive_fn: Function to ensure kernel is alive (MCP_SERVER)
            wait_for_kernel_idle_fn: Function to wait for kernel idle state (MCP_SERVER)
            extract_output_fn: Function to extract single output (MCP_SERVER)
            
        Returns:
            List of outputs including progress updates
        """
        if mode == ServerMode.JUPYTER_SERVER:
            # JUPYTER_SERVER mode: Use centralized local execution
            # Note: Streaming progress requires WebSocket (MCP_SERVER mode)
            # In JUPYTER_SERVER mode, we get final results without intermediate updates
            if serverapp is None:
                raise ValueError("serverapp is required for JUPYTER_SERVER mode")
            if kernel_manager is None:
                raise ValueError("kernel_manager is required for JUPYTER_SERVER mode")
            
            config = get_config()
            notebook_path = config.document_id
            kernel_id = config.runtime_id
            
            logger.info(f"Executing cell {cell_index} in JUPYTER_SERVER mode (timeout: {timeout_seconds}s)")
            logger.info("Note: Streaming progress updates require MCP_SERVER mode with WebSocket")
            
            return await execute_cell_local(
                serverapp=serverapp,
                notebook_path=notebook_path,
                cell_index=cell_index,
                kernel_id=kernel_id,
                timeout=timeout_seconds,
                logger=logger
            )
        
        elif mode == ServerMode.MCP_SERVER:
            # MCP_SERVER mode: Use WebSocket with real-time streaming
            if ensure_kernel_alive_fn is None:
                raise ValueError("ensure_kernel_alive_fn is required for MCP_SERVER mode")
            if wait_for_kernel_idle_fn is None:
                raise ValueError("wait_for_kernel_idle_fn is required for MCP_SERVER mode")
            if extract_output_fn is None:
                raise ValueError("extract_output_fn is required for MCP_SERVER mode")
            if notebook_manager is None:
                raise ValueError("notebook_manager is required for MCP_SERVER mode")
            
            kernel = ensure_kernel_alive_fn()
            await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
            
            outputs_log = []
            
            async with notebook_manager.get_current_connection() as notebook:
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
        else:
            raise ValueError(f"Invalid mode: {mode}")
