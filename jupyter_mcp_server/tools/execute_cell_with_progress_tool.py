# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute cell with progress monitoring tool."""

import asyncio
import logging
from typing import Union, List
from mcp.types import ImageContent

from ._base import BaseTool, ServerMode
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import execute_cell_local, get_current_notebook_context

logger = logging.getLogger(__name__)


class ExecuteCellWithProgressTool(BaseTool):
    """Execute a specific cell with timeout and progress monitoring.
    
    Supports both MCP_SERVER (with forced sync) and JUPYTER_SERVER modes.
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
        execute_cell_with_forced_sync_fn=None,
        **kwargs
    ) -> List[Union[str, ImageContent]]:
        """Execute a specific cell with timeout and progress monitoring.
        
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
            execute_cell_with_forced_sync_fn: Function to execute cell with forced sync (MCP_SERVER)
            
        Returns:
            List of outputs from the executed cell
        """
        if mode == ServerMode.JUPYTER_SERVER:
            # JUPYTER_SERVER mode: Use centralized local execution
            if serverapp is None:
                raise ValueError("serverapp is required for JUPYTER_SERVER mode")
            if kernel_manager is None:
                raise ValueError("kernel_manager is required for JUPYTER_SERVER mode")
            
            notebook_path, kernel_id = get_current_notebook_context(notebook_manager)
            
            logger.info(f"Executing cell {cell_index} with progress monitoring in JUPYTER_SERVER mode (timeout: {timeout_seconds}s)")
            
            # Note: In JUPYTER_SERVER mode, we use the same execution as simple timeout
            # since real-time progress monitoring requires WebSocket connection (MCP_SERVER mode)
            return await execute_cell_local(
                serverapp=serverapp,
                notebook_path=notebook_path,
                cell_index=cell_index,
                kernel_id=kernel_id,
                timeout=timeout_seconds,
                logger=logger
            )
        
        elif mode == ServerMode.MCP_SERVER:
            # MCP_SERVER mode: Use WebSocket with forced synchronization
            if ensure_kernel_alive_fn is None:
                raise ValueError("ensure_kernel_alive_fn is required for MCP_SERVER mode")
            if wait_for_kernel_idle_fn is None:
                raise ValueError("wait_for_kernel_idle_fn is required for MCP_SERVER mode")
            if safe_extract_outputs_fn is None:
                raise ValueError("safe_extract_outputs_fn is required for MCP_SERVER mode")
            if execute_cell_with_forced_sync_fn is None:
                raise ValueError("execute_cell_with_forced_sync_fn is required for MCP_SERVER mode")
            if notebook_manager is None:
                raise ValueError("notebook_manager is required for MCP_SERVER mode")
            
            kernel = ensure_kernel_alive_fn()
            await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
            
            async with notebook_manager.get_current_connection() as notebook:
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
        else:
            raise ValueError(f"Invalid mode: {mode}")
