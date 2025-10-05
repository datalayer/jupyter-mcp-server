# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import re
from typing import Any, Union
from mcp.types import ImageContent
from .config_env import ALLOW_IMG_OUTPUT


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
    
    # Handle CRDT YArray
    if hasattr(outputs, '__iter__') and not isinstance(outputs, (str, dict)):
        try:
            for output in outputs:
                extracted = extract_output(output)
                if extracted:
                    result.append(extracted)
        except Exception as e:
            result.append(f"[Error extracting output: {str(e)}]")
    else:
        # Handle single output or traditional list
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