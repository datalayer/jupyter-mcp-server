# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Insert and execute code cell tool implementation."""

import asyncio
import logging
import zmq.asyncio
from pathlib import Path
from inspect import isawaitable
from typing import Any, Optional, List, Union
from jupyter_server_api import JupyterServerClient
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.utils import get_current_notebook_context
from jupyter_mcp_server.utils import safe_extract_outputs
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
    
    async def _execute_via_execution_stack(
        self,
        serverapp: Any,
        kernel_id: str,
        code: str,
        document_id: Optional[str] = None,
        cell_id: Optional[str] = None,
        timeout: int = 300,
        poll_interval: float = 0.1
    ) -> List[Union[str, ImageContent]]:
        """Execute code using ExecutionStack (JUPYTER_SERVER mode with jupyter-server-nbmodel).
        
        This uses the ExecutionStack from jupyter-server-nbmodel extension directly,
        avoiding the reentrant HTTP call issue.
        
        Args:
            serverapp: Jupyter server application instance
            kernel_id: Kernel ID to execute in
            code: Code to execute
            document_id: Optional document ID for RTC integration
            cell_id: Optional cell ID for RTC integration
            timeout: Maximum time to wait for execution (seconds)
            poll_interval: Time between polling for results (seconds)
            
        Returns:
            List of formatted outputs
        """
        try:
            # Get the ExecutionStack from the jupyter_server_nbmodel extension
            nbmodel_extensions = serverapp.extension_manager.extension_apps.get("jupyter_server_nbmodel", set())
            if not nbmodel_extensions:
                raise RuntimeError("jupyter_server_nbmodel extension not found. Please install it.")
            
            nbmodel_ext = next(iter(nbmodel_extensions))
            execution_stack = nbmodel_ext._Extension__execution_stack
            
            # Build metadata for RTC integration if available
            metadata = {}
            if document_id and cell_id:
                metadata = {
                    "document_id": document_id,
                    "cell_id": cell_id
                }
            
            # Submit execution request
            logger.info(f"Submitting execution request to kernel {kernel_id}")
            request_id = execution_stack.put(kernel_id, code, metadata)
            logger.info(f"Execution request {request_id} submitted")
            
            # Poll for results
            start_time = asyncio.get_event_loop().time()
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(f"Execution timed out after {timeout} seconds")
                
                # Get result (returns None if pending, result dict if complete)
                result = execution_stack.get(kernel_id, request_id)
                
                if result is not None:
                    # Execution complete
                    logger.info(f"Execution request {request_id} completed")
                    
                    # Check for errors
                    if "error" in result:
                        error_info = result["error"]
                        logger.error(f"Execution error: {error_info}")
                        return [f"[ERROR: {error_info.get('ename', 'Unknown')}: {error_info.get('evalue', '')}]"]
                    
                    # Check for pending input (shouldn't happen with allow_stdin=False)
                    if "input_request" in result:
                        logger.warning("Unexpected input request during execution")
                        return ["[ERROR: Unexpected input request]"]
                    
                    # Extract outputs
                    outputs = result.get("outputs", [])
                    if outputs:
                        formatted = safe_extract_outputs(outputs)
                        logger.info(f"Execution completed with {len(formatted)} outputs")
                        return formatted
                    else:
                        logger.info("Execution completed with no outputs")
                        return ["[No output generated]"]
                
                # Still pending, wait before next poll
                await asyncio.sleep(poll_interval)
                
        except Exception as e:
            logger.error(f"Error executing via ExecutionStack: {e}", exc_info=True)
            return [f"[ERROR: {str(e)}]"]
    
    async def _execute_via_kernel_manager(
        self,
        kernel_manager,
        kernel_id: str,
        code: str,
        timeout: int,
        safe_extract_outputs_fn
    ) -> list[Union[str, ImageContent]]:
        """Execute code using kernel_manager (JUPYTER_SERVER mode - FALLBACK)."""
        try:
            # Get the kernel
            lkm = kernel_manager.pinned_superclass.get_kernel(kernel_manager, kernel_id)
            session = lkm.session
            client = lkm.client()
            
            # Ensure channels are started (critical for receiving IOPub messages!)
            if not client.channels_running:
                client.start_channels()
                # Wait for channels to be ready
                await asyncio.sleep(0.1)
            
            # Send execute request
            shell_channel = client.shell_channel
            msg_id = session.msg("execute_request", {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False,
                "stop_on_error": False
            })
            shell_channel.send(msg_id)
            
            # Prepare to collect outputs
            outputs = []
            execution_done = False
            
            # Poll for messages with timeout
            poller = zmq.asyncio.Poller()
            iopub_socket = client.iopub_channel.socket
            shell_socket = shell_channel.socket
            poller.register(iopub_socket, zmq.POLLIN)
            poller.register(shell_socket, zmq.POLLIN)
            
            timeout_ms = timeout * 1000
            start_time = asyncio.get_event_loop().time()
            
            while not execution_done:
                elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                remaining_ms = max(0, timeout_ms - elapsed_ms)
                
                if remaining_ms <= 0:
                    client.stop_channels()
                    return [f"[TIMEOUT ERROR: Execution exceeded {timeout} seconds]"]
                
                events = dict(await poller.poll(remaining_ms))
                
                # Check for shell reply (execution complete)
                if shell_socket in events:
                    reply = client.shell_channel.get_msg(timeout=0)
                    if isawaitable(reply):
                        reply = await reply
                    
                    if reply and reply.get('parent_header', {}).get('msg_id') == msg_id['header']['msg_id']:
                        execution_done = True
                
                # Check for IOPub messages (outputs)
                if iopub_socket in events:
                    msg = client.iopub_channel.get_msg(timeout=0)
                    if isawaitable(msg):
                        msg = await msg
                    
                    logger.debug(f"IOPub message received: msg_type={msg.get('msg_type')}, parent_id={msg.get('parent_header', {}).get('msg_id')}, expected_id={msg_id['header']['msg_id']}")
                    
                    if msg and msg.get('parent_header', {}).get('msg_id') == msg_id['header']['msg_id']:
                        msg_type = msg.get('msg_type')
                        content = msg.get('content', {})
                        
                        logger.debug(f"Processing IOPub message: msg_type={msg_type}, content={content}")
                        
                        # Collect output messages
                        if msg_type == 'stream':
                            outputs.append({
                                'output_type': 'stream',
                                'name': content.get('name', 'stdout'),
                                'text': content.get('text', '')
                            })
                        elif msg_type == 'execute_result':
                            outputs.append({
                                'output_type': 'execute_result',
                                'data': content.get('data', {}),
                                'metadata': content.get('metadata', {}),
                                'execution_count': content.get('execution_count')
                            })
                        elif msg_type == 'display_data':
                            outputs.append({
                                'output_type': 'display_data',
                                'data': content.get('data', {}),
                                'metadata': content.get('metadata', {})
                            })
                        elif msg_type == 'error':
                            outputs.append({
                                'output_type': 'error',
                                'ename': content.get('ename', ''),
                                'evalue': content.get('evalue', ''),
                                'traceback': content.get('traceback', [])
                            })
            
            # Clean up
            client.stop_channels()
            
            # Extract and format outputs
            logger.info(f"Execution (JUPYTER_SERVER) collected {len(outputs)} raw outputs: {outputs}")
            if outputs:
                result = safe_extract_outputs_fn(outputs)
                logger.info(f"Execution (JUPYTER_SERVER) completed with {len(result)} formatted outputs: {result}")
                return result
            else:
                logger.warning("Execution (JUPYTER_SERVER) completed with no outputs collected")
                return ["[No output generated]"]
                
        except Exception as e:
            logger.error(f"Error executing via kernel_manager: {e}")
            return [f"[ERROR: {str(e)}]"]
    
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
            return await self._execute_via_execution_stack(
                serverapp, kernel_id, cell_source, 
                document_id=document_id, 
                cell_id=inserted_cell_id,
                timeout=300
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
            
            # Then execute directly via ExecutionStack (without RTC metadata since notebook not open)
            return await self._execute_via_execution_stack(
                serverapp, kernel_id, cell_source, timeout=300
            )
            
            # Call the file-based insertion method directly
            await insert_tool._insert_cell_file(notebook_path, cell_index, "code", cell_source)
            
            # Then execute directly via kernel_manager
            return await self._execute_via_kernel_manager(
                kernel_manager, kernel_id, cell_source, 300, safe_extract_outputs_fn
            )
    
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
