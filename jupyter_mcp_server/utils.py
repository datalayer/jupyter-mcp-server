# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import re
from typing import Any, Union
from mcp.types import ImageContent
from .env import ALLOW_IMG_OUTPUT


def get_current_notebook_context(notebook_manager=None):
    """
    Get the current notebook path and kernel ID for JUPYTER_SERVER mode.
    
    Args:
        notebook_manager: NotebookManager instance (optional)
        
    Returns:
        Tuple of (notebook_path, kernel_id)
        Falls back to config values if notebook_manager not provided
    """
    from .config import get_config
    
    notebook_path = None
    kernel_id = None
    
    if notebook_manager:
        # Try to get current notebook info from manager
        notebook_path = notebook_manager.get_current_notebook_path()
        current_notebook = notebook_manager.get_current_notebook() or "default"
        kernel_id = notebook_manager.get_kernel_id(current_notebook)
    
    # Fallback to config if not found in manager
    if not notebook_path or not kernel_id:
        config = get_config()
        if not notebook_path:
            notebook_path = config.document_id
        if not kernel_id:
            kernel_id = config.runtime_id
    
    return notebook_path, kernel_id


def extract_output(output: Union[dict, Any]) -> Union[str, ImageContent]:
    """
    Extracts readable output from a Jupyter cell output dictionary.
    Handles both traditional and CRDT-based Jupyter formats.

    Args:
        output: The output from a Jupyter cell (dict or CRDT object).

    Returns:
        str: A string representation of the output.
    """
    # Handle pycrdt._text.Text objects
    if hasattr(output, 'source'):
        return str(output.source)
    
    # Handle CRDT YText objects
    if hasattr(output, '__str__') and 'Text' in str(type(output)):
        text_content = str(output)
        return strip_ansi_codes(text_content)
    
    # Handle lists (common in error tracebacks)
    if isinstance(output, list):
        return '\n'.join(extract_output(item) for item in output)
    
    # Handle traditional dictionary format
    if not isinstance(output, dict):
        return strip_ansi_codes(str(output))
    
    output_type = output.get("output_type")
    
    if output_type == "stream":
        text = output.get("text", "")
        if isinstance(text, list):
            text = ''.join(text)
        elif hasattr(text, 'source'):
            text = str(text.source)
        return strip_ansi_codes(str(text))
    
    elif output_type in ["display_data", "execute_result"]:
        data = output.get("data", {})
        if "image/png" in data:
            if ALLOW_IMG_OUTPUT:
                try:
                    return ImageContent(type="image", data=data["image/png"], mimeType="image/png")
                except Exception:
                    # Fallback to text placeholder on error
                    return "[Image Output (PNG) - Error processing image]"
            else:
                return "[Image Output (PNG) - Image display disabled]"
        if "text/plain" in data:
            plain_text = data["text/plain"]
            if hasattr(plain_text, 'source'):
                plain_text = str(plain_text.source)
            return strip_ansi_codes(str(plain_text))
        elif "text/html" in data:
            return "[HTML Output]"
        else:
            return f"[{output_type} Data: keys={list(data.keys())}]"
    
    elif output_type == "error":
        traceback = output.get("traceback", [])
        if isinstance(traceback, list):
            clean_traceback = []
            for line in traceback:
                if hasattr(line, 'source'):
                    line = str(line.source)
                clean_traceback.append(strip_ansi_codes(str(line)))
            return '\n'.join(clean_traceback)
        else:
            if hasattr(traceback, 'source'):
                traceback = str(traceback.source)
            return strip_ansi_codes(str(traceback))
    
    else:
        return f"[Unknown output type: {output_type}]"


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def _clean_notebook_outputs(notebook):
    """Remove transient fields from all cell outputs.
    
    The 'transient' field is part of the Jupyter kernel messaging protocol
    but is NOT part of the nbformat schema. This causes validation errors.
    
    Args:
        notebook: nbformat notebook object to clean (modified in place)
    """
    for cell in notebook.cells:
        if cell.cell_type == 'code' and hasattr(cell, 'outputs'):
            for output in cell.outputs:
                if isinstance(output, dict) and 'transient' in output:
                    del output['transient']


def safe_extract_outputs(outputs: Any) -> list[Union[str, ImageContent]]:
    """
    Safely extract all outputs from a cell, handling CRDT structures.
    
    Args:
        outputs: Cell outputs (could be CRDT YArray or traditional list)
        
    Returns:
        list[Union[str, ImageContent]]: List of outputs (strings or image content)
    """
    if not outputs:
        return []
    
    result = []
    
    # Handle CRDT YArray or list of outputs
    if hasattr(outputs, '__iter__') and not isinstance(outputs, (str, dict)):
        try:
            for output in outputs:
                extracted = extract_output(output)
                if extracted:
                    result.append(extracted)
        except Exception as e:
            result.append(f"[Error extracting output: {str(e)}]")
    else:
        # Handle single output
        extracted = extract_output(outputs)
        if extracted:
            result.append(extracted)
    
    return result


def format_cell_list(ydoc_cells: Any) -> str:
    """
    Format notebook cells into a readable table format.
    
    Args:
        ydoc_cells: The cells from the notebook's Y document
        
    Returns:
        str: Formatted table string with cell information
    """
    total_cells = len(ydoc_cells)
    
    if total_cells == 0:
        return "Notebook is empty, no cells found."
    
    # Create header
    lines = ["Index\tType\tCount\tFirst Line"]
    lines.append("-" * 60)  # Separator line
    
    # Process each cell
    for i, cell_data in enumerate(ydoc_cells):
        cell_type = cell_data.get("cell_type", "unknown")
        
        # Get execution count for code cells
        if cell_type == "code":
            execution_count = cell_data.get("execution_count") or "None"
        else:
            execution_count = "N/A"
        
        # Get first line of source
        source_lines = normalize_cell_source(cell_data.get("source", ""))
        first_line = source_lines[0] if source_lines else ""
        
        # Get just the first line and truncate if too long
        first_line = first_line.split('\n')[0]
        if len(first_line) > 50:
            first_line = first_line[:47] + "..."
        
        # Add to table
        lines.append(f"{i}\t{cell_type}\t{execution_count}\t{first_line}")
    
    return "\n".join(lines)

def normalize_cell_source(source: Any) -> list[str]:
    """
    Normalize cell source to a list of strings (lines).
    
    In Jupyter notebooks, source can be either:
    - A string (single or multi-line with \n)  
    - A list of strings (each element is a line)
    - CRDT text objects
    
    Args:
        source: The source from a Jupyter cell
        
    Returns:
        list[str]: List of source lines
    """
    if not source:
        return []
    
    # Handle CRDT text objects
    if hasattr(source, 'source'):
        source = str(source.source)
    elif hasattr(source, '__str__') and 'Text' in str(type(source)):
        source = str(source)
    
    # If it's already a list, return as is
    if isinstance(source, list):
        return [str(line) for line in source]
    
    # If it's a string, split by newlines
    if isinstance(source, str):
        # Split by newlines but preserve the newline characters except for the last line
        lines = source.splitlines(keepends=True)
        # Remove trailing newline from the last line if present
        if lines and lines[-1].endswith('\n'):
            lines[-1] = lines[-1][:-1]
        return lines
    
    # Fallback: convert to string and split
    return str(source).splitlines(keepends=True)


def get_surrounding_cells_info(notebook, cell_index: int, total_cells: int) -> str:
    """Get information about surrounding cells for context."""
    start_index = max(0, cell_index - 5)
    end_index = min(total_cells, cell_index + 6)
    
    if total_cells == 0:
        return "Notebook is now empty, no cells remaining"
    
    lines = ["Index\tType\tCount\tFirst Line"]
    lines.append("-" * 60)
    
    for i in range(start_index, end_index):
        if i >= total_cells:
            break
            
        ydoc = notebook._doc
        cell_data = ydoc._ycells[i]
        cell_type = cell_data.get("cell_type", "unknown")
        
        # Get execution count for code cells
        if cell_type == "code":
            execution_count = cell_data.get("execution_count") or "None"
        else:
            execution_count = "N/A"
        
        # Get first line of source
        source_lines = normalize_cell_source(cell_data.get("source", ""))
        first_line = source_lines[0] if source_lines else ""
        
        # Get just the first line and truncate if too long
        first_line = first_line.split('\n')[0]
        if len(first_line) > 50:
            first_line = first_line[:47] + "..."
        
        # Mark the target cell
        marker = " ← inserted" if i == cell_index else ""
        
        lines.append(f"{i}\t{cell_type}\t{execution_count}\t{first_line}{marker}")
    
    return "\n".join(lines)


###############################################################################
# Kernel and notebook operation helpers
###############################################################################


def create_kernel(config, logger):
    """Create a new kernel instance using current configuration."""
    from jupyter_kernel_client import KernelClient
    kernel = None
    try:
        # Initialize the kernel client with the provided parameters.
        kernel = KernelClient(
            server_url=config.runtime_url, 
            token=config.runtime_token, 
            kernel_id=config.runtime_id
        )
        kernel.start()
        logger.info("Kernel created and started successfully")
        return kernel
    except Exception as e:
        logger.error(f"Failed to create kernel: {e}")
        # Clean up partially initialized kernel to prevent __del__ errors
        if kernel is not None:
            try:
                # Try to clean up the kernel object if it exists
                if hasattr(kernel, 'stop'):
                    kernel.stop()
            except Exception as cleanup_error:
                logger.debug(f"Error during kernel cleanup: {cleanup_error}")
        raise


def start_kernel(notebook_manager, config, logger):
    """Start the Jupyter kernel with error handling (for backward compatibility)."""
    try:
        # Remove existing default notebook if any
        if "default" in notebook_manager:
            notebook_manager.remove_notebook("default")
        
        # Create and set up new kernel
        kernel = create_kernel(config, logger)
        notebook_manager.add_notebook("default", kernel)
        logger.info("Default notebook kernel started successfully")
    except Exception as e:
        logger.error(f"Failed to start kernel: {e}")
        raise


def ensure_kernel_alive(notebook_manager, current_notebook, create_kernel_fn):
    """Ensure kernel is running, restart if needed."""
    return notebook_manager.ensure_kernel_alive(current_notebook, create_kernel_fn)


async def execute_cell_with_timeout(notebook, cell_index, kernel, timeout_seconds, logger):
    """Execute a cell with timeout and real-time output sync."""
    import asyncio
    import time
    from concurrent.futures import ThreadPoolExecutor
    
    start_time = time.time()
    
    def _execute_sync():
        return notebook.execute_cell(cell_index, kernel)
    
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_execute_sync)
        
        while not future.done():
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                future.cancel()
                raise asyncio.TimeoutError(f"Cell execution timed out after {timeout_seconds} seconds")
            
            await asyncio.sleep(2)
            try:
                # Try to force document sync using the correct method
                ydoc = notebook._doc
                if hasattr(ydoc, 'flush') and callable(ydoc.flush):
                    ydoc.flush()  # Flush pending changes
                elif hasattr(notebook, '_websocket') and notebook._websocket:
                    # Force a small update to trigger sync
                    pass  # The websocket should auto-sync
                
                if cell_index < len(ydoc._ycells):
                    outputs = ydoc._ycells[cell_index].get("outputs", [])
                    if outputs:
                        logger.info(f"Cell {cell_index} executing... ({elapsed:.1f}s) - {len(outputs)} outputs so far")
            except Exception as e:
                logger.debug(f"Sync attempt failed: {e}")
                pass
        
        result = future.result()
        return result
        
    finally:
        executor.shutdown(wait=False)


async def execute_cell_with_forced_sync(notebook, cell_index, kernel, timeout_seconds, logger):
    """Execute cell with forced real-time synchronization."""
    import asyncio
    import time
    
    start_time = time.time()
    
    # Start execution
    execution_future = asyncio.create_task(
        asyncio.to_thread(notebook.execute_cell, cell_index, kernel)
    )
    
    last_output_count = 0
    
    while not execution_future.done():
        elapsed = time.time() - start_time
        
        if elapsed > timeout_seconds:
            execution_future.cancel()
            try:
                if hasattr(kernel, 'interrupt'):
                    kernel.interrupt()
            except Exception:
                pass
            raise asyncio.TimeoutError(f"Cell execution timed out after {timeout_seconds} seconds")
        
        # Check for new outputs and try to trigger sync
        try:
            ydoc = notebook._doc
            current_outputs = ydoc._ycells[cell_index].get("outputs", [])
            
            if len(current_outputs) > last_output_count:
                last_output_count = len(current_outputs)
                logger.info(f"Cell {cell_index} progress: {len(current_outputs)} outputs after {elapsed:.1f}s")
                
                # Try different sync methods
                try:
                    # Method 1: Force Y-doc update
                    if hasattr(ydoc, 'observe') and hasattr(ydoc, 'unobserve'):
                        # Trigger observers by making a tiny change
                        pass
                        
                    # Method 2: Force websocket message
                    if hasattr(notebook, '_websocket') and notebook._websocket:
                        # The websocket should automatically sync on changes
                        pass
                        
                except Exception as sync_error:
                    logger.debug(f"Sync method failed: {sync_error}")
                    
        except Exception as e:
            logger.debug(f"Output check failed: {e}")
        
        await asyncio.sleep(1)  # Check every second
    
    # Get final result
    try:
        await execution_future
    except asyncio.CancelledError:
        pass
    
    return None


def is_kernel_busy(kernel):
    """Check if kernel is currently executing something."""
    try:
        # This is a simple check - you might need to adapt based on your kernel client
        if hasattr(kernel, '_client') and hasattr(kernel._client, 'is_alive'):
            return kernel._client.is_alive()
        return False
    except Exception:
        return False


async def wait_for_kernel_idle(kernel, logger, max_wait_seconds=60):
    """Wait for kernel to become idle before proceeding."""
    import asyncio
    import time
    
    start_time = time.time()
    while is_kernel_busy(kernel):
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            logger.warning(f"Kernel still busy after {max_wait_seconds}s, proceeding anyway")
            break
        logger.info(f"Waiting for kernel to become idle... ({elapsed:.1f}s)")
        await asyncio.sleep(1)


async def safe_notebook_operation(operation_func, logger, max_retries=3):
    """Safely execute notebook operations with connection recovery."""
    import asyncio
    
    for attempt in range(max_retries):
        try:
            return await operation_func()
        except Exception as e:
            error_msg = str(e).lower()
            if any(err in error_msg for err in ["websocketclosederror", "connection is already closed", "connection closed"]):
                if attempt < max_retries - 1:
                    logger.warning(f"Connection lost, retrying... (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(1 + attempt)  # Increasing delay
                    continue
                else:
                    logger.error(f"Failed after {max_retries} attempts: {e}")
                    raise Exception(f"Connection failed after {max_retries} retries: {e}")
            else:
                # Non-connection error, don't retry
                raise e
    
    raise Exception("Unexpected error in retry logic")


def list_files_recursively(server_client, current_path="", current_depth=0, files=None, max_depth=3):
    """Recursively list all files and directories in the Jupyter server."""
    if files is None:
        files = []
    
    # Stop if we've reached max depth
    if current_depth > max_depth:
        return files
    
    try:
        contents = server_client.contents.list_directory(current_path)
        for item in contents:
            full_path = f"{current_path}/{item.name}" if current_path else item.name
            
            # Format size
            size_str = ""
            if hasattr(item, 'size') and item.size is not None:
                if item.size < 1024:
                    size_str = f"{item.size}B"
                elif item.size < 1024 * 1024:
                    size_str = f"{item.size // 1024}KB"
                else:
                    size_str = f"{item.size // (1024 * 1024)}MB"
            
            # Format last modified
            last_modified = ""
            if hasattr(item, 'last_modified') and item.last_modified:
                last_modified = item.last_modified.strftime("%Y-%m-%d %H:%M:%S")
            
            # Add file/directory to list
            files.append({
                'path': full_path,
                'type': item.type,
                'size': size_str,
                'last_modified': last_modified
            })
            
            # Recursively explore directories
            if item.type == "directory":
                list_files_recursively(server_client, full_path, current_depth + 1, files, max_depth)
                
    except Exception as e:
        # If we can't access a directory, add an error entry
        files.append({
            'path': current_path or "root",
            'type': "error",
            'size': "",
            'last_modified': f"Error: {str(e)}"
        })
    
    return files


###############################################################################
# Local code execution helpers (JUPYTER_SERVER mode)
###############################################################################


async def execute_via_execution_stack(
    serverapp: Any,
    kernel_id: str,
    code: str,
    document_id: str = None,
    cell_id: str = None,
    timeout: int = 300,
    poll_interval: float = 0.1,
    logger = None
) -> list[Union[str, ImageContent]]:
    """Execute code using ExecutionStack (JUPYTER_SERVER mode with jupyter-server-nbmodel).
    
    This uses the ExecutionStack from jupyter-server-nbmodel extension directly,
    avoiding the reentrant HTTP call issue. This is the preferred method for code
    execution in JUPYTER_SERVER mode.
    
    Args:
        serverapp: Jupyter server application instance
        kernel_id: Kernel ID to execute in
        code: Code to execute
        document_id: Optional document ID for RTC integration (format: json:notebook:<file_id>)
        cell_id: Optional cell ID for RTC integration
        timeout: Maximum time to wait for execution (seconds)
        poll_interval: Time between polling for results (seconds)
        logger: Logger instance (optional)
        
    Returns:
        List of formatted outputs (strings or ImageContent)
        
    Raises:
        RuntimeError: If jupyter-server-nbmodel extension is not installed
        TimeoutError: If execution exceeds timeout
    """
    import asyncio
    import logging as default_logging
    
    if logger is None:
        logger = default_logging.getLogger(__name__)
    
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
                
                # Parse JSON string if needed (ExecutionStack returns JSON string)
                if isinstance(outputs, str):
                    import json
                    try:
                        outputs = json.loads(outputs)
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse outputs JSON: {outputs}")
                        return [f"[ERROR: Invalid output format]"]
                
                if outputs:
                    formatted = safe_extract_outputs(outputs)
                    logger.info(f"Execution completed with {len(formatted)} formatted outputs: {formatted}")
                    return formatted
                else:
                    logger.info("Execution completed with no outputs")
                    return ["[No output generated]"]
            
            # Still pending, wait before next poll
            await asyncio.sleep(poll_interval)
            
    except Exception as e:
        logger.error(f"Error executing via ExecutionStack: {e}", exc_info=True)
        return [f"[ERROR: {str(e)}]"]


async def execute_code_local(
    serverapp,
    notebook_path: str,
    code: str,
    kernel_id: str,
    timeout: int = 300,
    logger=None
) -> list[Union[str, ImageContent]]:
    """Execute code in a kernel and return outputs (JUPYTER_SERVER mode).
    
    This is a centralized code execution function for JUPYTER_SERVER mode that:
    1. Gets the kernel from kernel_manager
    2. Creates a client and sends execute_request
    3. Polls for response messages with timeout
    4. Collects and formats outputs
    5. Cleans up resources
    
    Args:
        serverapp: Jupyter ServerApp instance
        notebook_path: Path to the notebook (for context)
        code: Code to execute
        kernel_id: ID of the kernel to execute in
        timeout: Timeout in seconds (default: 300)
        logger: Logger instance (optional)
        
    Returns:
        List of formatted outputs (strings or ImageContent)
    """
    import asyncio
    import zmq.asyncio
    from inspect import isawaitable
    
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
    
    try:
        # Get kernel manager
        kernel_manager = serverapp.kernel_manager
        
        # Get the kernel using pinned_superclass pattern (like KernelUsageHandler)
        lkm = kernel_manager.pinned_superclass.get_kernel(kernel_manager, kernel_id)
        session = lkm.session
        client = lkm.client()
        
        # Ensure channels are started (critical for receiving IOPub messages!)
        if not client.channels_running:
            client.start_channels()
            # Wait for channels to be ready
            await asyncio.sleep(0.1)
        
        # Send execute request on shell channel
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
        
        # Give a moment for messages to start flowing
        await asyncio.sleep(0.01)
        
        # Prepare to collect outputs
        outputs = []
        execution_done = False
        grace_period_ms = 100  # Wait 100ms after shell reply for remaining IOPub messages
        execution_done_time = None
        
        # Poll for messages with timeout
        poller = zmq.asyncio.Poller()
        iopub_socket = client.iopub_channel.socket
        shell_socket = shell_channel.socket
        poller.register(iopub_socket, zmq.POLLIN)
        poller.register(shell_socket, zmq.POLLIN)
        
        timeout_ms = timeout * 1000
        start_time = asyncio.get_event_loop().time()
        
        while not execution_done or (execution_done_time and (asyncio.get_event_loop().time() - execution_done_time) * 1000 < grace_period_ms):
            elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            remaining_ms = max(0, timeout_ms - elapsed_ms)
            
            # If execution is done and grace period expired, exit
            if execution_done and execution_done_time and (asyncio.get_event_loop().time() - execution_done_time) * 1000 >= grace_period_ms:
                break
            
            if remaining_ms <= 0:
                client.stop_channels()
                logger.warning(f"Code execution timeout after {timeout}s, collected {len(outputs)} outputs")
                return [f"[TIMEOUT ERROR: Code execution exceeded {timeout} seconds]"]
            
            # Use shorter poll timeout during grace period
            poll_timeout = min(remaining_ms, grace_period_ms / 2) if execution_done else remaining_ms
            events = dict(await poller.poll(poll_timeout))
            
            if not events:
                continue  # No messages, continue polling
            
            # IMPORTANT: Process IOPub messages BEFORE shell to collect outputs before marking done
            # Check for IOPub messages (outputs)
            if iopub_socket in events:
                msg = client.iopub_channel.get_msg(timeout=0)
                # Handle async get_msg (like KernelUsageHandler)
                if isawaitable(msg):
                    msg = await msg
                
                if msg and msg.get('parent_header', {}).get('msg_id') == msg_id['header']['msg_id']:
                    msg_type = msg.get('msg_type')
                    content = msg.get('content', {})
                    
                    logger.debug(f"IOPub message: {msg_type}")
                    
                    # Collect output messages
                    if msg_type == 'stream':
                        outputs.append({
                            'output_type': 'stream',
                            'name': content.get('name', 'stdout'),
                            'text': content.get('text', '')
                        })
                        logger.debug(f"Collected stream output: {len(content.get('text', ''))} chars")
                    elif msg_type == 'execute_result':
                        outputs.append({
                            'output_type': 'execute_result',
                            'data': content.get('data', {}),
                            'metadata': content.get('metadata', {}),
                            'execution_count': content.get('execution_count')
                        })
                        logger.debug(f"Collected execute_result, count: {content.get('execution_count')}")
                    elif msg_type == 'display_data':
                        # Note: 'transient' field from kernel messages is NOT part of nbformat schema
                        # Only include 'output_type', 'data', and 'metadata' fields
                        outputs.append({
                            'output_type': 'display_data',
                            'data': content.get('data', {}),
                            'metadata': content.get('metadata', {})
                        })
                        logger.debug("Collected display_data")
                    elif msg_type == 'error':
                        outputs.append({
                            'output_type': 'error',
                            'ename': content.get('ename', ''),
                            'evalue': content.get('evalue', ''),
                            'traceback': content.get('traceback', [])
                        })
                        logger.debug(f"Collected error: {content.get('ename')}")
            
            # Check for shell reply (execution complete) - AFTER processing IOPub
            if shell_socket in events:
                reply = client.shell_channel.get_msg(timeout=0)
                # Handle async get_msg (like KernelUsageHandler)
                if isawaitable(reply):
                    reply = await reply
                
                if reply and reply.get('parent_header', {}).get('msg_id') == msg_id['header']['msg_id']:
                    logger.debug(f"Execution complete, reply status: {reply.get('content', {}).get('status')}")
                    execution_done = True
                    execution_done_time = asyncio.get_event_loop().time()
        
        # Clean up
        client.stop_channels()
        
        # Extract and format outputs
        if outputs:
            result = safe_extract_outputs(outputs)
            logger.info(f"Code execution completed with {len(result)} outputs")
            return result
        else:
            return ["[No output generated]"]
            
    except Exception as e:
        logger.error(f"Error executing code locally: {e}")
        return [f"[ERROR: {str(e)}]"]


async def execute_cell_local(
    serverapp,
    notebook_path: str,
    cell_index: int,
    kernel_id: str,
    timeout: int = 300,
    logger=None
) -> list[Union[str, ImageContent]]:
    """Execute a cell in a notebook and return outputs (JUPYTER_SERVER mode).
    
    This function:
    1. Reads the cell source from the notebook (YDoc or file)
    2. Executes the code using execute_code_local
    3. Writes the outputs back to the notebook (YDoc or file)
    4. Returns the formatted outputs
    
    Args:
        serverapp: Jupyter ServerApp instance
        notebook_path: Path to the notebook
        cell_index: Index of the cell to execute
        kernel_id: ID of the kernel to execute in
        timeout: Timeout in seconds (default: 300)
        logger: Logger instance (optional)
        
    Returns:
        List of formatted outputs (strings or ImageContent)
    """
    import nbformat
    
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
    
    try:
        # Try to get YDoc first (for collaborative editing)
        file_id_manager = serverapp.web_app.settings.get("file_id_manager")
        ydoc = None
        
        if file_id_manager:
            file_id = file_id_manager.get_id(notebook_path)
            yroom_manager = serverapp.web_app.settings.get("yroom_manager")
            
            if yroom_manager:
                room_id = f"json:notebook:{file_id}"
                if yroom_manager.has_room(room_id):
                    try:
                        yroom = yroom_manager.get_room(room_id)
                        ydoc = await yroom.get_jupyter_ydoc()
                        logger.info(f"Using YDoc for cell {cell_index} execution")
                    except Exception as e:
                        logger.debug(f"Could not get YDoc: {e}")
        
        # Execute using YDoc or file
        if ydoc:
            # YDoc path - read from collaborative document
            if cell_index < 0 or cell_index >= len(ydoc.ycells):
                raise ValueError(f"Cell index {cell_index} out of range. Notebook has {len(ydoc.ycells)} cells.")
            
            cell = ydoc.ycells[cell_index]
            
            # Only execute code cells
            cell_type = cell.get("cell_type", "")
            if cell_type != "code":
                return [f"[Cell {cell_index} is not a code cell (type: {cell_type})]"]
            
            source_raw = cell.get("source", "")
            if isinstance(source_raw, list):
                source = "".join(source_raw)
            else:
                source = str(source_raw)
            
            if not source:
                return ["[Cell is empty]"]
            
            logger.info(f"Cell {cell_index} source from YDoc: {source[:100]}...")
            
            # Execute the code
            outputs = await execute_code_local(
                serverapp=serverapp,
                notebook_path=notebook_path,
                code=source,
                kernel_id=kernel_id,
                timeout=timeout,
                logger=logger
            )
            
            logger.info(f"Execution completed with {len(outputs)} outputs: {outputs}")
            
            # Update execution count in YDoc
            max_count = 0
            for c in ydoc.ycells:
                if c.get("cell_type") == "code" and c.get("execution_count"):
                    max_count = max(max_count, c["execution_count"])
            
            cell["execution_count"] = max_count + 1
            
            # Update outputs in YDoc (simplified - just store formatted strings)
            # YDoc outputs should match nbformat structure
            cell["outputs"] = []
            for output in outputs:
                if isinstance(output, str):
                    cell["outputs"].append({
                        "output_type": "stream",
                        "name": "stdout",
                        "text": output
                    })
            
            return outputs
        else:
            # File path - original logic
            # Read notebook as version 4 (latest) for consistency
            with open(notebook_path, 'r', encoding='utf-8') as f:
                notebook = nbformat.read(f, as_version=4)
            
            # Clean transient fields from outputs
            _clean_notebook_outputs(notebook)
            
            # Validate cell index
            if cell_index < 0 or cell_index >= len(notebook.cells):
                raise ValueError(f"Cell index {cell_index} out of range. Notebook has {len(notebook.cells)} cells.")
        
        cell = notebook.cells[cell_index]
        
        # Only execute code cells
        if cell.cell_type != 'code':
            return [f"[Cell {cell_index} is not a code cell (type: {cell.cell_type})]"]
        
        # Get cell source
        source = cell.source
        if not source:
            return ["[Cell is empty]"]
        
        # Execute the code
        logger.info(f"Executing cell {cell_index} from {notebook_path}")
        outputs = await execute_code_local(
            serverapp=serverapp,
            notebook_path=notebook_path,
            code=source,
            kernel_id=kernel_id,
            timeout=timeout,
            logger=logger
        )
        
        # Write outputs back to notebook (update execution_count and outputs)
        # Get the last execution count
        max_count = 0
        for c in notebook.cells:
            if c.cell_type == 'code' and c.execution_count:
                max_count = max(max_count, c.execution_count)
        
        cell.execution_count = max_count + 1
        
        # Convert formatted outputs back to nbformat structure
        # Note: outputs is already formatted, so we need to reconstruct
        # For simplicity, we'll store a simple representation
        cell.outputs = []
        for output in outputs:
            if isinstance(output, str):
                # Create a stream output
                cell.outputs.append(nbformat.v4.new_output(
                    output_type='stream',
                    name='stdout',
                    text=output
                ))
            elif isinstance(output, ImageContent):
                # Create a display_data output with image
                cell.outputs.append(nbformat.v4.new_output(
                    output_type='display_data',
                    data={'image/png': output.data}
                ))
        
        # Write notebook back
        with open(notebook_path, 'w', encoding='utf-8') as f:
            nbformat.write(notebook, f)
        
        logger.info(f"Cell {cell_index} executed and notebook updated")
        return outputs
        
    except Exception as e:
        logger.error(f"Error executing cell locally: {e}")
        return [f"[ERROR: {str(e)}]"]