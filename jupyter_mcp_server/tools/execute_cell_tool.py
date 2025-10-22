# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Unified execute cell tool with configurable streaming."""

import asyncio
import logging
import time
import nbformat
from pathlib import Path
from typing import Union, List
from mcp.types import ImageContent

from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.utils import (
    get_current_notebook_context,
    execute_via_execution_stack,
    safe_extract_outputs,
    get_jupyter_ydoc,
    clean_notebook_outputs,
    wait_for_kernel_idle,
    safe_extract_outputs,
    execute_cell_with_forced_sync,
    extract_output
)

logger = logging.getLogger(__name__)


class ExecuteCellTool(BaseTool):
    """Execute a cell with configurable timeout and optional streaming progress updates"""

    async def _write_outputs_to_cell(
        self,
        notebook_path: str,
        cell_index: int,
        outputs: List[Union[str, ImageContent]]
    ):
        """Write execution outputs back to a notebook cell."""

        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=4)

        clean_notebook_outputs(notebook)

        # Handle negative indices (e.g., -1 for last cell)
        num_cells = len(notebook.cells)
        if cell_index < 0:
            cell_index = num_cells + cell_index
        
        if cell_index < 0 or cell_index >= num_cells:
            logger.warning(f"Cell index {cell_index} out of range (notebook has {num_cells} cells), cannot write outputs")
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
        timeout_seconds: int = 60,
        stream: bool = False,
        progress_interval: int = 5,
        ensure_kernel_alive_fn=None,
        **kwargs
    ) -> List[Union[str, ImageContent]]:
        """Execute a cell with configurable timeout and optional streaming progress updates.

        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            serverapp: ServerApp instance for JUPYTER_SERVER mode
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager for MCP_SERVER mode
            cell_index: Index of the cell to execute (0-based)
            timeout_seconds: Maximum seconds to wait for execution
            stream: Enable streaming progress updates for long-running cells
            progress_interval: Seconds between progress updates when stream=True
            ensure_kernel_alive_fn: Function to ensure kernel is alive (MCP_SERVER)

        Returns:
            List of outputs from the executed cell
        """
        if mode == ServerMode.JUPYTER_SERVER:
            # JUPYTER_SERVER mode: Use ExecutionStack with YDoc awareness
            from jupyter_mcp_server.jupyter_extension.context import get_server_context

            context = get_server_context()
            serverapp = context.serverapp

            if serverapp is None:
                raise ValueError("serverapp is required for JUPYTER_SERVER mode")
            if kernel_manager is None:
                raise ValueError("kernel_manager is required for JUPYTER_SERVER mode")

            notebook_path, kernel_id = get_current_notebook_context(notebook_manager)

            # Check if kernel needs to be started
            if kernel_id is None:
                # No kernel available - start a new one on demand
                logger.info("No kernel_id available, starting new kernel for execute_cell")
                kernel_id = await kernel_manager.start_kernel()

                # Wait a bit for kernel to initialize
                await asyncio.sleep(1.0)
                logger.info(f"Kernel {kernel_id} started and initialized")

                # Store the kernel in notebook_manager if available
                if notebook_manager is not None:
                    kernel_info = {"id": kernel_id}
                    notebook_manager.add_notebook(
                        name=notebook_path,
                        kernel=kernel_info,
                        server_url="local",
                        path=notebook_path
                    )

            logger.info(f"Executing cell {cell_index} in JUPYTER_SERVER mode (timeout: {timeout_seconds}s)")

            # Resolve to absolute path
            if serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)

            # Get file_id from file_id_manager
            file_id_manager = serverapp.web_app.settings.get("file_id_manager")
            if file_id_manager is None:
                raise RuntimeError("file_id_manager not available in serverapp")

            file_id = file_id_manager.get_id(notebook_path)
            if file_id is None:
                file_id = file_id_manager.index(notebook_path)

            # Try to get YDoc if notebook is open
            ydoc = await get_jupyter_ydoc(serverapp, file_id)

            if ydoc:
                # Notebook is open - use YDoc and RTC
                logger.info(f"Notebook {file_id} is open, using RTC mode")
                
                num_cells = len(ydoc.ycells)
                if cell_index >= num_cells:
                    raise ValueError(f"Cell index {cell_index} out of range (notebook has {num_cells} cells)")

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

                return outputs
            else:
                # Notebook not open - use file-based approach
                logger.info(f"Notebook {file_id} not open, using file mode")

                with open(notebook_path, 'r', encoding='utf-8') as f:
                    notebook = nbformat.read(f, as_version=4)

                num_cells = len(notebook.cells)
                if cell_index >= num_cells:
                    raise ValueError(f"Cell index {cell_index} out of range (notebook has {num_cells} cells)")

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

                return outputs

        elif mode == ServerMode.MCP_SERVER:
            kernel = ensure_kernel_alive_fn()
            await wait_for_kernel_idle(kernel, max_wait_seconds=30)

            async with notebook_manager.get_current_connection() as notebook:
                num_cells = len(notebook)
                if cell_index >= num_cells:
                    raise ValueError(f"Cell index {cell_index} out of range (notebook has {num_cells} cells)")

                if stream:
                    # Streaming mode: Real-time monitoring with progress updates
                    logger.info(f"Executing cell {cell_index} in streaming mode (timeout: {timeout_seconds}s, interval: {progress_interval}s)")

                    outputs_log = []

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
                            current_outputs = notebook[cell_index].get("outputs", [])
                            if len(current_outputs) > last_output_count:
                                new_outputs = current_outputs[last_output_count:]
                                for output in new_outputs:
                                    extracted = extract_output(output)
                                    if isinstance(extracted, str):
                                        outputs_log.append(f"[{elapsed:.1f}s] {extracted}")
                                    else:
                                        outputs_log.append(f"[{elapsed:.1f}s]")
                                        outputs_log.append(extracted)
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
                            final_outputs = notebook[cell_index].get("outputs", [])
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

                else:
                    # Non-streaming mode: Use forced synchronization
                    logger.info(f"Starting execution of cell {cell_index} with {timeout_seconds}s timeout")

                    try:
                        # Use the forced sync function
                        await execute_cell_with_forced_sync(notebook, cell_index, kernel, timeout_seconds)

                        # Get final outputs
                        outputs = notebook[cell_index].get("outputs", [])
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
                            outputs = notebook[cell_index].get("outputs", [])
                            partial_outputs = safe_extract_outputs(outputs)
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
