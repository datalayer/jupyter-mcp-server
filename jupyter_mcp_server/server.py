# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import asyncio
import logging
from typing import Union

import click
import httpx
import uvicorn
from fastapi import Request
from jupyter_kernel_client import KernelClient
from jupyter_nbmodel_client import (
    NbModelClient,
    get_notebook_websocket_url,
)
from mcp.server import FastMCP
from starlette.responses import JSONResponse

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from jupyter_mcp_server.models import RoomRuntime
from jupyter_mcp_server.utils import extract_output, safe_extract_outputs


###############################################################################


logger = logging.getLogger(__name__)


###############################################################################


TRANSPORT: str = "stdio"
PROVIDER: str = "jupyter"

RUNTIME_URL: str = "http://localhost:8888"
START_NEW_RUNTIME: bool = False
RUNTIME_ID: str | None = None
RUNTIME_TOKEN: str | None = None

ROOM_URL: str = "http://localhost:8888"
ROOM_ID: str = "notebook.ipynb"
ROOM_TOKEN: str | None = None


###############################################################################


mcp = FastMCP(name="Jupyter MCP Server", json_response=False, stateless_http=True)

kernel = None


###############################################################################


def _start_kernel():
    """Start the Jupyter kernel with error handling."""
    global kernel
    try:
        if kernel:
            kernel.stop()
    except Exception as e:
        logger.warning(f"Error stopping existing kernel: {e}")
    
    try:
        # Initialize the kernel client with the provided parameters.
        kernel = KernelClient(server_url=RUNTIME_URL, token=RUNTIME_TOKEN, kernel_id=RUNTIME_ID)
        kernel.start()
        logger.info("Kernel started successfully")
    except Exception as e:
        logger.error(f"Failed to start kernel: {e}")
        kernel = None
        raise


def _ensure_kernel_alive():
    """Ensure kernel is running, restart if needed."""
    global kernel
    if kernel is None:
        logger.info("Kernel is None, starting new kernel")
        _start_kernel()
    elif not hasattr(kernel, 'is_alive') or not kernel.is_alive():
        logger.info("Kernel is not alive, restarting")
        _start_kernel()


async def execute_cell_with_timeout(notebook, cell_index, kernel, timeout_seconds=300):
    """Execute a cell with timeout and real-time output sync."""
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


# Alternative approach: Create a custom execution function that forces updates
async def execute_cell_with_forced_sync(notebook, cell_index, kernel, timeout_seconds=300):
    """Execute cell with forced real-time synchronization."""
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


async def wait_for_kernel_idle(kernel, max_wait_seconds=60):
    """Wait for kernel to become idle before proceeding."""
    start_time = time.time()
    while is_kernel_busy(kernel):
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            logger.warning(f"Kernel still busy after {max_wait_seconds}s, proceeding anyway")
            break
        logger.info(f"Waiting for kernel to become idle... ({elapsed:.1f}s)")
        await asyncio.sleep(1)


async def safe_notebook_operation(operation_func, max_retries=3):
    """Safely execute notebook operations with connection recovery."""
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


###############################################################################
# Custom Routes.


@mcp.custom_route("/api/connect", ["PUT"])
async def connect(request: Request):
    """Connect to a room and a runtime from the Jupyter MCP server."""

    data = await request.json()
    logger.info("Connecting to room_runtime:", data)

    room_runtime = RoomRuntime(**data)

    global kernel
    if kernel:
        try:
            kernel.stop()
        except Exception as e:
            logger.warning(f"Error stopping kernel during connect: {e}")

    global PROVIDER
    PROVIDER = room_runtime.provider

    global RUNTIME_URL
    RUNTIME_URL = room_runtime.runtime_url
    global RUNTIME_ID
    RUNTIME_ID = room_runtime.runtime_id
    global RUNTIME_TOKEN
    RUNTIME_TOKEN = room_runtime.runtime_token

    global ROOM_URL
    ROOM_URL = room_runtime.room_url
    global ROOM_ID
    ROOM_ID = room_runtime.room_id
    global ROOM_TOKEN
    ROOM_TOKEN = room_runtime.room_token

    try:
        _start_kernel()
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@mcp.custom_route("/api/stop", ["DELETE"])
async def stop():
    global kernel
    try:
        if kernel:
            await kernel.stop()
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Error stopping kernel: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@mcp.custom_route("/api/healthz", ["GET"])
async def health_check():
    """Custom health check endpoint"""
    kernel_status = "unknown"
    try:
        if kernel:
            kernel_status = "alive" if hasattr(kernel, 'is_alive') and kernel.is_alive() else "dead"
        else:
            kernel_status = "not_initialized"
    except Exception:
        kernel_status = "error"
    
    return JSONResponse(
        {
            "success": True,
            "service": "jupyter-mcp-server",
            "message": "Jupyter MCP Server is running.",
            "status": "healthy",
            "kernel_status": kernel_status,
        }
    )


###############################################################################
# Tools.


@mcp.tool()
async def append_markdown_cell(cell_source: str) -> str:
    """Append at the end of the notebook a markdown cell with the provided source.

    Args:
        cell_source: Markdown source

    Returns:
        str: Success message
    """
    async def _append_markdown():
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()
            notebook.add_markdown_cell(cell_source)
            return "Jupyter Markdown cell added."
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in append_markdown_cell: {e}")
    
    return await safe_notebook_operation(_append_markdown)


@mcp.tool()
async def insert_markdown_cell(cell_index: int, cell_source: str) -> str:
    """Insert a markdown cell in a Jupyter notebook.

    Args:
        cell_index: Index of the cell to insert (0-based)
        cell_source: Markdown source

    Returns:
        str: Success message
    """
    async def _insert_markdown():
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()
            notebook.insert_markdown_cell(cell_index, cell_source)
            return f"Jupyter Markdown cell {cell_index} inserted."
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in insert_markdown_cell: {e}")
    
    return await safe_notebook_operation(_insert_markdown)


@mcp.tool()
async def overwrite_cell_source(cell_index: int, cell_source: str) -> str:
    """Overwrite the source of an existing cell.
       Note this does not execute the modified cell by itself.

    Args:
        cell_index: Index of the cell to overwrite (0-based)
        cell_source: New cell source - must match existing cell type

    Returns:
        str: Success message
    """
    async def _overwrite_cell():
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()
            notebook.set_cell_source(cell_index, cell_source)
            return f"Cell {cell_index} overwritten successfully - use execute_cell to execute it if code"
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in overwrite_cell_source: {e}")
    
    return await safe_notebook_operation(_overwrite_cell)


@mcp.tool()
async def append_execute_code_cell(cell_source: str) -> list[str]:
    """Append at the end of the notebook a code cell with the provided source and execute it.

    Args:
        cell_source: Code source

    Returns:
        list[str]: List of outputs from the executed cell
    """
    async def _append_execute():
        _ensure_kernel_alive()
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()
            cell_index = notebook.add_code_cell(cell_source)
            notebook.execute_cell(cell_index, kernel)

            ydoc = notebook._doc
            outputs = ydoc._ycells[cell_index]["outputs"]
            return safe_extract_outputs(outputs)
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in append_execute_code_cell: {e}")
    
    return await safe_notebook_operation(_append_execute)


@mcp.tool()
async def insert_execute_code_cell(cell_index: int, cell_source: str) -> list[str]:
    """Insert and execute a code cell in a Jupyter notebook.

    Args:
        cell_index: Index of the cell to insert (0-based)
        cell_source: Code source

    Returns:
        list[str]: List of outputs from the executed cell
    """
    async def _insert_execute():
        _ensure_kernel_alive()
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()
            notebook.insert_code_cell(cell_index, cell_source)
            notebook.execute_cell(cell_index, kernel)

            ydoc = notebook._doc
            outputs = ydoc._ycells[cell_index]["outputs"]
            return safe_extract_outputs(outputs)
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in insert_execute_code_cell: {e}")
    
    return await safe_notebook_operation(_insert_execute)


@mcp.tool()
async def execute_cell_with_progress(cell_index: int, timeout_seconds: int = 300) -> list[str]:
    """Execute a specific cell with timeout and progress monitoring.
    Args:
        cell_index: Index of the cell to execute (0-based)
        timeout_seconds: Maximum time to wait for execution (default: 300s)
    Returns:
        list[str]: List of outputs from the executed cell
    """
    async def _execute():
        _ensure_kernel_alive()
        await wait_for_kernel_idle(kernel, max_wait_seconds=30)
        
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()

            ydoc = notebook._doc

            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )

            logger.info(f"Starting execution of cell {cell_index} with {timeout_seconds}s timeout")
            
            # Use the corrected timeout function
            await execute_cell_with_forced_sync(notebook, cell_index, kernel, timeout_seconds)

            # Get final outputs
            ydoc = notebook._doc
            outputs = ydoc._ycells[cell_index]["outputs"]
            result = safe_extract_outputs(outputs)
            
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
                if notebook:
                    ydoc = notebook._doc
                    outputs = ydoc._ycells[cell_index].get("outputs", [])
                    partial_outputs = safe_extract_outputs(outputs)
                    partial_outputs.append(f"[TIMEOUT ERROR: Execution exceeded {timeout_seconds} seconds]")
                    return partial_outputs
            except Exception:
                pass
            
            return [f"[TIMEOUT ERROR: Cell execution exceeded {timeout_seconds} seconds and was interrupted]"]
            
        except Exception as e:
            logger.error(f"Error executing cell {cell_index}: {e}")
            raise
            
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in execute_cell_with_progress: {e}")
    
    return await safe_notebook_operation(_execute, max_retries=1)

# Simpler real-time monitoring without forced sync
@mcp.tool()
async def execute_cell_simple_timeout(cell_index: int, timeout_seconds: int = 300) -> list[str]:
    """Execute a cell with simple timeout (no forced real-time sync).
    This won't force real-time updates but will work reliably.
    """
    async def _execute():
        _ensure_kernel_alive()
        await wait_for_kernel_idle(kernel, max_wait_seconds=30)
        
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()

            ydoc = notebook._doc
            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(f"Cell index {cell_index} is out of range.")

            logger.info(f"Starting execution of cell {cell_index} with {timeout_seconds}s timeout")
            
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
            result = safe_extract_outputs(outputs)
            
            logger.info(f"Cell {cell_index} completed successfully")
            return result
            
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook: {e}")
    
    return await safe_notebook_operation(_execute, max_retries=1)

@mcp.tool()
async def execute_cell_streaming(cell_index: int, timeout_seconds: int = 300, progress_interval: int = 5) -> list[str]:
    """Execute cell with streaming progress updates.
    Args:
        cell_index: Index of the cell to execute (0-based)
        timeout_seconds: Maximum time to wait for execution (default: 300s)  
        progress_interval: Seconds between progress updates (default: 5s)
    Returns:
        list[str]: List of outputs including progress updates
    """
    async def _execute_streaming():
        _ensure_kernel_alive()
        await wait_for_kernel_idle(kernel, max_wait_seconds=30)
        
        notebook = None
        outputs_log = []
        
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()

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
                            extracted = extract_output(output)
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
                            extracted = extract_output(output)
                            if extracted.strip():
                                outputs_log.append(extracted)
                                
                except Exception as e:
                    outputs_log.append(f"[ERROR: {e}]")
            
            return outputs_log if outputs_log else ["[No output generated]"]
            
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    outputs_log.append(f"[Warning: Error closing notebook: {e}]")
    
    return await safe_notebook_operation(_execute_streaming, max_retries=1)

@mcp.tool()
async def read_all_cells() -> list[dict[str, Union[str, int, list[str]]]]:
    """Read all cells from the Jupyter notebook.
    Returns:
        list[dict]: List of cell information including index, type, source,
                    and outputs (for code cells)
    """
    async def _read_all():
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()

            ydoc = notebook._doc
            cells = []

            for i, cell in enumerate(ydoc._ycells):
                cell_info = {
                    "index": i,
                    "type": cell.get("cell_type", "unknown"),
                    "source": cell.get("source", ""),
                }

                # Add outputs for code cells
                if cell.get("cell_type") == "code":
                    try:
                        outputs = cell.get("outputs", [])
                        cell_info["outputs"] = safe_extract_outputs(outputs)
                    except Exception as e:
                        cell_info["outputs"] = [f"[Error reading outputs: {str(e)}]"]

                cells.append(cell_info)

            return cells
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in read_all_cells: {e}")
    
    return await safe_notebook_operation(_read_all)


@mcp.tool()
async def read_cell(cell_index: int) -> dict[str, Union[str, int, list[str]]]:
    """Read a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to read (0-based)
    Returns:
        dict: Cell information including index, type, source, and outputs (for code cells)
    """
    async def _read_cell():
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()

            ydoc = notebook._doc

            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )

            cell = ydoc._ycells[cell_index]
            cell_info = {
                "index": cell_index,
                "type": cell.get("cell_type", "unknown"),
                "source": cell.get("source", ""),
            }

            # Add outputs for code cells.
            if cell.get("cell_type") == "code":
                try:
                    outputs = cell.get("outputs", [])
                    cell_info["outputs"] = safe_extract_outputs(outputs)
                except Exception as e:
                    cell_info["outputs"] = [f"[Error reading outputs: {str(e)}]"]

            return cell_info
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in read_cell: {e}")
    
    return await safe_notebook_operation(_read_cell)


@mcp.tool()
async def get_notebook_info() -> dict[str, Union[str, int, dict[str, int]]]:
    """Get basic information about the notebook.
    Returns:
        dict: Notebook information including path, total cells, and cell type counts
    """
    async def _get_info():
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()

            ydoc = notebook._doc
            total_cells: int = len(ydoc._ycells)

            cell_types: dict[str, int] = {}
            for cell in ydoc._ycells:
                cell_type: str = str(cell.get("cell_type", "unknown"))
                cell_types[cell_type] = cell_types.get(cell_type, 0) + 1

            info: dict[str, Union[str, int, dict[str, int]]] = {
                "room_id": ROOM_ID,
                "total_cells": total_cells,
                "cell_types": cell_types,
            }

            return info
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in get_notebook_info: {e}")
    
    return await safe_notebook_operation(_get_info)


@mcp.tool()
async def delete_cell(cell_index: int) -> str:
    """Delete a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to delete (0-based)
    Returns:
        str: Success message
    """
    async def _delete_cell():
        notebook = None
        try:
            notebook = NbModelClient(
                get_notebook_websocket_url(
                    server_url=ROOM_URL, token=ROOM_TOKEN, path=ROOM_ID, provider=PROVIDER
                )
            )
            await notebook.start()

            ydoc = notebook._doc

            if cell_index < 0 or cell_index >= len(ydoc._ycells):
                raise ValueError(
                    f"Cell index {cell_index} is out of range. Notebook has {len(ydoc._ycells)} cells."
                )

            cell_type = ydoc._ycells[cell_index].get("cell_type", "unknown")

            # Delete the cell
            del ydoc._ycells[cell_index]

            return f"Cell {cell_index} ({cell_type}) deleted successfully."
        finally:
            if notebook:
                try:
                    await notebook.stop()
                except Exception as e:
                    logger.warning(f"Error stopping notebook in delete_cell: {e}")
    
    return await safe_notebook_operation(_delete_cell)


###############################################################################
# Commands.


@click.group()
def server():
    """Manages Jupyter MCP Server."""
    pass


@server.command("connect")
@click.option(
    "--provider",
    envvar="PROVIDER",
    type=click.Choice(["jupyter", "datalayer"]),
    default="jupyter",
    help="The provider to use for the room and runtime. Defaults to 'jupyter'.",
)
@click.option(
    "--runtime-url",
    envvar="RUNTIME_URL",
    type=click.STRING,
    default="http://localhost:8888",
    help="The runtime URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer runtime URL.",
)
@click.option(
    "--runtime-id",
    envvar="RUNTIME_ID",
    type=click.STRING,
    default=None,
    help="The kernel ID to use. If not provided, a new kernel should be started.",
)
@click.option(
    "--runtime-token",
    envvar="RUNTIME_TOKEN",
    type=click.STRING,
    default=None,
    help="The runtime token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
)
@click.option(
    "--room-url",
    envvar="ROOM_URL",
    type=click.STRING,
    default="http://localhost:8888",
    help="The room URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer room URL.",
)
@click.option(
    "--room-id",
    envvar="ROOM_ID",
    type=click.STRING,
    default="notebook.ipynb",
    help="The room id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path.",
)
@click.option(
    "--room-token",
    envvar="ROOM_TOKEN",
    type=click.STRING,
    default=None,
    help="The room token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
)
@click.option(
    "--jupyter-mcp-server-url",
    envvar="JUPYTER_MCP_SERVER_URL",
    type=click.STRING,
    default="http://localhost:4040",
    help="The URL of the Jupyter MCP Server to connect to. Defaults to 'http://localhost:4040'.",
)
def connect_command(
    jupyter_mcp_server_url: str,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    room_url: str,
    room_id: str,
    room_token: str,
    provider: str,
):
    """Command to connect a Jupyter MCP Server to a room and a runtime."""

    global PROVIDER
    PROVIDER = provider

    global RUNTIME_URL
    RUNTIME_URL = runtime_url
    global RUNTIME_ID
    RUNTIME_ID = runtime_id
    global RUNTIME_TOKEN
    RUNTIME_TOKEN = runtime_token

    global ROOM_URL
    ROOM_URL = room_url
    global ROOM_ID
    ROOM_ID = room_id
    global ROOM_TOKEN
    ROOM_TOKEN = room_token

    room_runtime = RoomRuntime(
        provider=PROVIDER,
        runtime_url=RUNTIME_URL,
        runtime_id=RUNTIME_ID,
        runtime_token=RUNTIME_TOKEN,
        room_url=ROOM_URL,
        room_id=ROOM_ID,
        room_token=ROOM_TOKEN,
    )

    r = httpx.put(
        f"{jupyter_mcp_server_url}/api/connect",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        content=room_runtime.model_dump_json(),
    )
    r.raise_for_status()


@server.command("stop")
@click.option(
    "--jupyter-mcp-server-url",
    envvar="JUPYTER_MCP_SERVER_URL",
    type=click.STRING,
    default="http://localhost:4040",
    help="The URL of the Jupyter MCP Server to stop. Defaults to 'http://localhost:4040'.",
)
def stop_command(jupyter_mcp_server_url: str):
    r = httpx.delete(
        f"{jupyter_mcp_server_url}/api/stop",
    )
    r.raise_for_status()


@server.command("start")
@click.option(
    "--transport",
    envvar="TRANSPORT",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="The transport to use for the MCP server. Defaults to 'stdio'.",
)
@click.option(
    "--provider",
    envvar="PROVIDER",
    type=click.Choice(["jupyter", "datalayer"]),
    default="jupyter",
    help="The provider to use for the room and runtime. Defaults to 'jupyter'.",
)
@click.option(
    "--runtime-url",
    envvar="RUNTIME_URL",
    type=click.STRING,
    default="http://localhost:8888",
    help="The runtime URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer runtime URL.",
)
@click.option(
    "--start-new-runtime",
    envvar="START_NEW_RUNTIME",
    type=click.BOOL,
    default=True,
    help="Start a new runtime or use an existing one.",
)
@click.option(
    "--runtime-id",
    envvar="RUNTIME_ID",
    type=click.STRING,
    default=None,
    help="The kernel ID to use. If not provided, a new kernel should be started.",
)
@click.option(
    "--runtime-token",
    envvar="RUNTIME_TOKEN",
    type=click.STRING,
    default=None,
    help="The runtime token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
)
@click.option(
    "--room-url",
    envvar="ROOM_URL",
    type=click.STRING,
    default="http://localhost:8888",
    help="The room URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer room URL.",
)
@click.option(
    "--room-id",
    envvar="ROOM_ID",
    type=click.STRING,
    default="notebook.ipynb",
    help="The room id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path.",
)
@click.option(
    "--room-token",
    envvar="ROOM_TOKEN",
    type=click.STRING,
    default=None,
    help="The room token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
)
@click.option(
    "--port",
    envvar="PORT",
    type=click.INT,
    default=4040,
    help="The port to use for the Streamable HTTP transport. Ignored for stdio transport.",
)
def start_command(
    transport: str,
    start_new_runtime: bool,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    room_url: str,
    room_id: str,
    room_token: str,
    port: int,
    provider: str,
):
    """Start the Jupyter MCP server with a transport."""

    global TRANSPORT
    TRANSPORT = transport

    global PROVIDER
    PROVIDER = provider

    global RUNTIME_URL
    RUNTIME_URL = runtime_url
    global START_NEW_RUNTIME
    START_NEW_RUNTIME = start_new_runtime
    global RUNTIME_ID
    RUNTIME_ID = runtime_id
    global RUNTIME_TOKEN
    RUNTIME_TOKEN = runtime_token

    global ROOM_URL
    ROOM_URL = room_url
    global ROOM_ID
    ROOM_ID = room_id
    global ROOM_TOKEN
    ROOM_TOKEN = room_token

    if START_NEW_RUNTIME or RUNTIME_ID:
        try:
            _start_kernel()
        except Exception as e:
            logger.error(f"Failed to start kernel on startup: {e}")

    logger.info(f"Starting Jupyter MCP Server with transport: {transport}")

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=port)  # noqa: S104
    else:
        raise Exception("Transport should be `stdio` or `streamable-http`.")


###############################################################################
# Main.


if __name__ == "__main__":
    start_command()