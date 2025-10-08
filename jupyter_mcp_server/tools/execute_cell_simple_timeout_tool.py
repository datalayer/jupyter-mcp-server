# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute cell with simple timeout tool."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, Union, List
from mcp.types import ImageContent

from ._base import BaseTool, ServerMode
from jupyter_mcp_server.config import get_config
from jupyter_mcp_server.utils import get_current_notebook_context, execute_via_execution_stack, safe_extract_outputs

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
    
    async def _get_jupyter_ydoc(self, serverapp: Any, file_id: str):
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
        
        # Convert formatted outputs to nbformat structure
        cell.outputs = []
        for output in outputs:
            if isinstance(output, ImageContent):
                cell.outputs.append(nbformat.v4.new_output(
                    output_type='display_data',
                    data={output.mimeType: output.data},
                    metadata={}
                ))
            elif isinstance(output, str):
                if output.startswith('[ERROR:') or output.startswith('[TIMEOUT ERROR:'):
                    cell.outputs.append(nbformat.v4.new_output(
                        output_type='stream',
                        name='stderr',
                        text=output
                    ))
                else:
                    cell.outputs.append(nbformat.v4.new_output(
                        output_type='execute_result',
                        data={'text/plain': output},
                        metadata={},
                        execution_count=None
                    ))
        
        # Update execution count
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
            # JUPYTER_SERVER mode: Use ExecutionStack with YDoc/RTC integration
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            
            context = get_server_context()
            serverapp = context.serverapp
            
            if serverapp is None:
                raise ValueError("serverapp is required for JUPYTER_SERVER mode")
            if kernel_manager is None:
                raise ValueError("kernel_manager is required for JUPYTER_SERVER mode")
            
            notebook_path, kernel_id = get_current_notebook_context(notebook_manager)
            
            # Resolve to absolute path
            if serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)
            
            # Check if kernel needs to be started
            if kernel_id is None:
                logger.info("No kernel_id available, starting new kernel for execute_cell_simple_timeout")
                kernel_id = await kernel_manager.start_kernel()
                
                await asyncio.sleep(1.0)
                logger.info(f"Kernel {kernel_id} started and initialized")
                
                if notebook_manager is not None:
                    kernel_info = {"id": kernel_id}
                    notebook_manager.add_notebook(
                        name=notebook_path,
                        kernel=kernel_info,
                        server_url="local",
                        path=notebook_path
                    )
            
            logger.info(f"Executing cell {cell_index} in JUPYTER_SERVER mode (timeout: {timeout_seconds}s)")
            
            # Get file_id for YDoc lookup
            file_id_manager = serverapp.web_app.settings.get("file_id_manager")
            if file_id_manager is None:
                raise RuntimeError("file_id_manager not available in serverapp")
            
            file_id = file_id_manager.get_id(notebook_path)
            
            # Try to get YDoc
            ydoc = await self._get_jupyter_ydoc(serverapp, file_id)
            
            if ydoc:
                # Notebook is open in collaborative mode, use YDoc with RTC
                if cell_index < 0 or cell_index >= len(ydoc.ycells):
                    raise ValueError(f"Cell index {cell_index} out of range. Notebook has {len(ydoc.ycells)} cells.")
                
                ycell = ydoc.ycells[cell_index]
                cell_id = ycell.get("id")
                
                # Get cell source
                source_raw = ycell.get("source", "")
                if isinstance(source_raw, list):
                    cell_source = "".join(source_raw)
                else:
                    cell_source = str(source_raw)
                
                if not cell_source:
                    return ["[Cell is empty]"]
                
                document_id = f"json:notebook:{file_id}"
                
                # Execute via ExecutionStack with RTC metadata
                return await execute_via_execution_stack(
                    serverapp, kernel_id, cell_source,
                    document_id=document_id,
                    cell_id=cell_id,
                    timeout=timeout_seconds,
                    logger=logger
                )
            else:
                # YDoc not available - use file operations
                logger.info("YDoc not available, using file operations + ExecutionStack execution fallback")
                
                # Read cell source from file
                import nbformat
                with open(notebook_path, 'r', encoding='utf-8') as f:
                    notebook = nbformat.read(f, as_version=4)
                
                if cell_index < 0 or cell_index >= len(notebook.cells):
                    raise ValueError(f"Cell index {cell_index} out of range. Notebook has {len(notebook.cells)} cells.")
                
                cell = notebook.cells[cell_index]
                if cell.cell_type != 'code':
                    return [f"[Cell {cell_index} is not a code cell (type: {cell.cell_type})]"]
                
                cell_source = cell.source
                if not cell_source:
                    return ["[Cell is empty]"]
                
                # Execute via ExecutionStack (without RTC metadata)
                outputs = await execute_via_execution_stack(
                    serverapp, kernel_id, cell_source,
                    timeout=timeout_seconds,
                    logger=logger
                )
                
                # Write outputs back to file
                logger.info(f"Writing {len(outputs)} outputs back to notebook cell {cell_index}")
                await self._write_outputs_to_cell(notebook_path, cell_index, outputs)
                
                return outputs
        
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
