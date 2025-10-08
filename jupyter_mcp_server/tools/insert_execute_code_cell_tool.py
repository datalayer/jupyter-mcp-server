# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Insert and execute code cell tool implementation."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional, List, Union
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context, safe_extract_outputs, execute_via_execution_stack
from mcp.types import ImageContent

logger = logging.getLogger(__name__)


class InsertExecuteCodeCellTool(BaseTool):
    """Tool to insert and execute a code cell."""
    
    @property
    def name(self) -> str:
        return "insert_execute_code_cell"
    
    @property
    def description(self) -> str:
        return """Insert and execute a code cell in a Jupyter notebook.

Args:
    cell_index: Index of the cell to insert (0-based). Use -1 to append at end and execute.
    cell_source: Code source

Returns:
    list[Union[str, ImageContent]]: List of outputs from the executed cell"""
    
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
    
    async def _insert_execute_ydoc(
        self,
        serverapp: Any,
        notebook_path: str,
        cell_index: int,
        cell_source: str,
        kernel_manager,
        kernel_id: str,
        safe_extract_outputs_fn
    ) -> List[Union[str, ImageContent]]:
        """Insert and execute cell using YDoc (collaborative editing mode)."""
        # Get file_id from file_id_manager
        file_id_manager = serverapp.web_app.settings.get("file_id_manager")
        if file_id_manager is None:
            raise RuntimeError("file_id_manager not available in serverapp")
        
        file_id = file_id_manager.get_id(notebook_path)
        
        # Try to get YDoc
        ydoc = await self._get_jupyter_ydoc(serverapp, file_id)
        
        if ydoc:
            # Notebook is open in collaborative mode, use YDoc
            total_cells = len(ydoc.ycells)
            actual_index = cell_index if cell_index != -1 else total_cells
            
            if actual_index < 0 or actual_index > total_cells:
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {total_cells} cells. Use -1 to append at end."
                )
            
            # Create and insert the cell
            cell = {
                "cell_type": "code",
                "source": cell_source,
            }
            ycell = ydoc.create_ycell(cell)
            
            if actual_index >= total_cells:
                ydoc.ycells.append(ycell)
            else:
                ydoc.ycells.insert(actual_index, ycell)
            
            # Get the inserted cell's ID for RTC metadata
            inserted_cell_id = ycell.get("id")
            
            # Build document_id for RTC (format: json:notebook:<file_id>)
            document_id = f"json:notebook:{file_id}"
            
            # Execute the cell using ExecutionStack with RTC metadata
            # This will automatically update the cell outputs in the YDoc
            return await execute_via_execution_stack(
                serverapp, kernel_id, cell_source, 
                document_id=document_id, 
                cell_id=inserted_cell_id,
                timeout=300,
                logger=logger
            )
        else:
            # YDoc not available - use file operations + direct kernel execution
            # This path is used when notebook is not open in JupyterLab but we still have kernel access
            logger.info("YDoc not available, using file operations + ExecutionStack execution fallback")
            
            # Insert cell using file operations
            from jupyter_mcp_server.tools.insert_cell_tool import InsertCellTool
            insert_tool = InsertCellTool()
            
            # Call the file-based insertion method directly
            await insert_tool._insert_cell_file(notebook_path, cell_index, "code", cell_source)
            
            # Calculate actual index where cell was inserted
            import nbformat
            with open(notebook_path, 'r', encoding='utf-8') as f:
                notebook = nbformat.read(f, as_version=4)
            total_cells = len(notebook.cells)
            actual_index = cell_index if cell_index != -1 else total_cells - 1
            
            # Then execute directly via ExecutionStack (without RTC metadata since notebook not open)
            outputs = await execute_via_execution_stack(
                serverapp, kernel_id, cell_source, timeout=300, logger=logger
            )
            
            # CRITICAL: Write outputs back to the notebook file so they're visible in UI
            logger.info(f"Writing {len(outputs)} outputs back to notebook cell {actual_index}")
            await self._write_outputs_to_cell(notebook_path, actual_index, outputs)
            
            return outputs
    
    async def _insert_execute_websocket(
        self,
        notebook_manager: NotebookManager,
        cell_index: int,
        cell_source: str,
        ensure_kernel_alive
    ) -> List[Union[str, ImageContent]]:
        """Insert and execute cell using WebSocket connection (MCP_SERVER mode)."""
        # Ensure kernel is alive
        if ensure_kernel_alive:
            kernel = ensure_kernel_alive()
        else:
            # Fallback: get kernel from notebook_manager
            current_notebook = notebook_manager.get_current_notebook() or "default"
            kernel = notebook_manager.get_kernel(current_notebook)
            if not kernel:
                raise RuntimeError("No kernel available for execution")
        
        async with notebook_manager.get_current_connection() as notebook:
            ydoc = notebook._doc
            total_cells = len(ydoc._ycells)
            
            actual_index = cell_index if cell_index != -1 else total_cells
                
            if actual_index < 0 or actual_index > total_cells:
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {total_cells} cells. Use -1 to append at end."
                )
            
            if actual_index == total_cells:
                notebook.add_code_cell(cell_source)
            else:
                notebook.insert_code_cell(actual_index, cell_source)
                
            notebook.execute_cell(actual_index, kernel)

            ydoc = notebook._doc
            outputs = ydoc._ycells[actual_index]["outputs"]
            return safe_extract_outputs(outputs)
    
    async def _write_outputs_to_cell(
        self,
        notebook_path: str,
        cell_index: int,
        outputs: List[Union[str, ImageContent]]
    ):
        """Write execution outputs back to a notebook cell.
        
        This is critical for making outputs visible in JupyterLab when using
        file-based execution (when YDoc/RTC is not available).
        
        Args:
            notebook_path: Path to the notebook file
            cell_index: Index of the cell to update
            outputs: List of output strings or ImageContent objects
        """
        import nbformat
        from jupyter_mcp_server.utils import _clean_notebook_outputs
        
        # Read the notebook
        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=4)
        
        # Clean any transient fields
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
                # Image output
                cell.outputs.append(nbformat.v4.new_output(
                    output_type='display_data',
                    data={output.mimeType: output.data},
                    metadata={}
                ))
            elif isinstance(output, str):
                # Text output - determine if it's an error or regular output
                if output.startswith('[ERROR:') or output.startswith('[TIMEOUT ERROR:'):
                    # Error output
                    cell.outputs.append(nbformat.v4.new_output(
                        output_type='stream',
                        name='stderr',
                        text=output
                    ))
                else:
                    # Regular output (assume execute_result for simplicity)
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
        
        # Write back to file
        with open(notebook_path, 'w', encoding='utf-8') as f:
            nbformat.write(notebook, f)
        
        logger.info(f"Wrote {len(outputs)} outputs to cell {cell_index} in {notebook_path}")
    
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
        cell_index: int = None,
        cell_source: str = None,
        # Helper function passed from server.py
        ensure_kernel_alive = None,
        **kwargs
    ) -> List[Union[str, ImageContent]]:
        """Execute the insert_execute_code_cell tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            cell_index: Index to insert cell (0-based, -1 to append)
            cell_source: Code source
            ensure_kernel_alive: Function to ensure kernel is alive
            **kwargs: Additional parameters
            
        Returns:
            List of outputs from the executed cell
        """
        if mode == ServerMode.JUPYTER_SERVER and kernel_manager is not None:
            # JUPYTER_SERVER mode: Use YDoc and kernel_manager
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            from jupyter_mcp_server.config import get_config
            
            context = get_server_context()
            serverapp = context.serverapp
            
            notebook_path, kernel_id = get_current_notebook_context(notebook_manager)
            
            # Resolve to absolute path FIRST
            if serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)
            
            if kernel_id is None:
                # No kernel available - start a new one on demand
                logger.info("No kernel_id available, starting new kernel for insert_execute_code_cell")
                kernel_id = await kernel_manager.start_kernel()
                
                # Wait a bit for kernel to initialize
                await asyncio.sleep(1.0)
                logger.info(f"Kernel {kernel_id} started and initialized")
                
                # Store the kernel with ABSOLUTE path in notebook_manager
                if notebook_manager is not None:
                    kernel_info = {"id": kernel_id}
                    notebook_manager.add_notebook(
                        name=notebook_path,
                        kernel=kernel_info,
                        server_url="local",
                        path=notebook_path
                    )
            
            if serverapp:
                return await self._insert_execute_ydoc(
                    serverapp, notebook_path, cell_index, cell_source,
                    kernel_manager, kernel_id, safe_extract_outputs
                )
            else:
                raise RuntimeError("serverapp not available in JUPYTER_SERVER mode")
                
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            # MCP_SERVER mode: Use WebSocket connection
            return await self._insert_execute_websocket(
                notebook_manager, cell_index, cell_source, ensure_kernel_alive
            )
        else:
            raise ValueError(f"Invalid mode or missing required clients: mode={mode}")
