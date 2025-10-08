# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute cell with streaming progress updates tool."""

import asyncio
import time
import logging
from pathlib import Path
from typing import Union, List
from mcp.types import ImageContent

from ._base import BaseTool, ServerMode
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import get_current_notebook_context, execute_via_execution_stack, safe_extract_outputs

logger = logging.getLogger(__name__)


class ExecuteCellStreamingTool(BaseTool):
    """Execute cell with streaming progress updates.
    
    To be used for long-running cells. Provides real-time progress monitoring
    in MCP_SERVER mode via WebSocket. In JUPYTER_SERVER mode, uses ExecutionStack.
    """
    
    @property
    def name(self) -> str:
        return "execute_cell_streaming"
    
    @property
    def description(self) -> str:
        return "Execute cell with streaming progress updates (for long-running cells)"
    
    async def _get_jupyter_ydoc(self, serverapp, file_id: str):
        """Get the YNotebook document if it's currently open in a collaborative session."""
        try:
            yroom_manager = serverapp.web_app.settings.get("yroom_manager")
            if yroom_manager is None:
                return None
                
            room_id = f"json:notebook:{file_id}"
            
            if yroom_manager.has_room(room_id):
                yroom = yroom_manager.get_room(room_id)
                notebook = await yroom.get_jupyter_ydoc()
                return notebook
        except Exception:
            pass
        
        return None
    
    async def _write_outputs_to_cell(
        self,
        notebook_path: str,
        cell_index: int,
        outputs: List[Union[str, ImageContent]]
    ):
        """Write execution outputs back to a notebook cell."""
        import nbformat
        from jupyter_mcp_server.utils import _clean_notebook_outputs
        
        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=4)
        
        _clean_notebook_outputs(notebook)
        
        if cell_index < 0 or cell_index >= len(notebook.cells):
            logger.warning(f"Cell index {cell_index} out of range, cannot write outputs")
            return
        
        cell = notebook.cells[cell_index]
        if cell.cell_type != 'code':
            logger.warning(f"Cell {cell_index} is not a code cell, cannot write outputs")
            return
        
        cell.outputs = []
        for output in outputs:
            if isinstance(output, ImageContent):
                cell.outputs.append(nbformat.v4.new_output(
                    output_type='display_data',
                    data={output.mimeType: output.data},
                    metadata={}
                ))
            elif isinstance(output, str):
                if output.startswith('[ERROR:') or output.startswith('[TIMEOUT ERROR:') or output.startswith('[PROGRESS:'):
                    cell.outputs.append(nbformat.v4.new_output(
                        output_type='stream',
                        name='stdout',
                        text=output
                    ))
                else:
                    cell.outputs.append(nbformat.v4.new_output(
                        output_type='execute_result',
                        data={'text/plain': output},
                        metadata={},
                        execution_count=None
                    ))
        
        max_count = 0
        for c in notebook.cells:
            if c.cell_type == 'code' and c.execution_count:
                max_count = max(max_count, c.execution_count)
        cell.execution_count = max_count + 1
        
        with open(notebook_path, 'w', encoding='utf-8') as f:
            nbformat.write(notebook, f)
        
        logger.info(f"Wrote {len(outputs)} outputs to cell {cell_index} in {notebook_path}")
    
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
            # JUPYTER_SERVER mode: Use ExecutionStack with YDoc awareness
            # Note: Streaming progress requires WebSocket (MCP_SERVER mode)
            # In JUPYTER_SERVER mode, we get final results without intermediate updates
            if serverapp is None:
                raise ValueError("serverapp is required for JUPYTER_SERVER mode")
            if kernel_manager is None:
                raise ValueError("kernel_manager is required for JUPYTER_SERVER mode")
            
            notebook_path, kernel_id = get_current_notebook_context(notebook_manager)
            
            # Resolve to absolute path
            if serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)
            
            logger.info(f"Executing cell {cell_index} in JUPYTER_SERVER mode (timeout: {timeout_seconds}s)")
            logger.info("Note: Streaming progress updates require MCP_SERVER mode with WebSocket")
            
            # Get file_id from file_id_manager
            file_id_manager = serverapp.web_app.settings.get("file_id_manager")
            if file_id_manager is None:
                raise RuntimeError("file_id_manager not available in serverapp")
            
            file_id = file_id_manager.get_id(notebook_path)
            if file_id is None:
                file_id = file_id_manager.index(notebook_path)
            
            # Try to get YDoc if notebook is open
            ydoc = await self._get_jupyter_ydoc(serverapp, file_id)
            
            if ydoc:
                # Notebook is open - use YDoc and RTC
                logger.info(f"Notebook {file_id} is open, using RTC mode")
                
                if cell_index < 0 or cell_index >= len(ydoc.ycells):
                    raise ValueError(f"Cell index {cell_index} out of range")
                
                cell_id = ydoc.ycells[cell_index].get("id")
                cell_source = ydoc.ycells[cell_index].get("source")
                
                if not cell_source or not cell_source.to_py().strip():
                    return []
                
                code_to_execute = cell_source.to_py()
                document_id = f"json:notebook:{file_id}"
                
                # Execute with RTC metadata - outputs will sync automatically
                outputs = await execute_via_execution_stack(
                    serverapp=serverapp,
                    kernel_id=kernel_id,
                    code=code_to_execute,
                    document_id=document_id,
                    cell_id=cell_id,
                    timeout=timeout_seconds
                )
                
                return safe_extract_outputs(outputs)
            else:
                # Notebook not open - use file-based approach
                logger.info(f"Notebook {file_id} not open, using file mode")
                
                import nbformat
                with open(notebook_path, 'r', encoding='utf-8') as f:
                    notebook = nbformat.read(f, as_version=4)
                
                if cell_index < 0 or cell_index >= len(notebook.cells):
                    raise ValueError(f"Cell index {cell_index} out of range")
                
                cell = notebook.cells[cell_index]
                if cell.cell_type != 'code':
                    raise ValueError(f"Cell {cell_index} is not a code cell")
                
                code_to_execute = cell.source
                if not code_to_execute.strip():
                    return []
                
                # Execute without RTC metadata
                outputs = await execute_via_execution_stack(
                    serverapp=serverapp,
                    kernel_id=kernel_id,
                    code=code_to_execute,
                    timeout=timeout_seconds
                )
                
                # Write outputs back to file
                await self._write_outputs_to_cell(notebook_path, cell_index, outputs)
                
                return safe_extract_outputs(outputs)
        
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
