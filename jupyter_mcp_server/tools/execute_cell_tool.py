# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unified execute cell tool with configurable streaming."""

import asyncio
import logging
import time
import nbformat
from pathlib import Path
from typing import Optional, Union, List
from mcp.types import ImageContent

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
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
    track_pending_execution,
    extract_output,
    extract_kernelspec_from_notebook
)

logger = logging.getLogger(__name__)


class ExecuteCellTool(BaseTool):
    """Execute a cell with configurable timeout and optional streaming progress updates"""

    async def _write_outputs_to_cell(
        self,
        notebook_path: str,
        cell_index: int,
        outputs: List[Union[str, ImageContent]],
        raw_outputs: Optional[List[dict]] = None
    ):
        """Write execution outputs back to a notebook cell.

        When raw_outputs is given, the kernel's own nbformat-shaped outputs are
        persisted, which keeps each output's real output_type. Without them only
        the formatted strings are available (the timeout path, for example), and
        the output type can only be guessed from the string form.
        """

        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=4)

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

        if raw_outputs:
            # The kernel already reported each output's type: keep it.
            cell.outputs = [nbformat.from_dict(output) for output in raw_outputs]
        else:
            # Only the formatted strings are available, so the type has to be
            # guessed from the string form.
            cell.outputs = []
            for output in outputs:
                if isinstance(output, ImageContent):
                    cell.outputs.append(nbformat.v4.new_output(
                        output_type='display_data',
                        data={output.mimeType: output.data},
                        metadata={}
                    ))
                elif isinstance(output, str):
                    if output == '[No output generated]':
                        # A display-only sentinel for the tool response (see
                        # execute_via_execution_stack in utils.py): a cell that
                        # produced nothing must persist no output, not a
                        # fabricated execute_result.
                        continue
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

        # Strip kernel-protocol fields that are not part of the nbformat schema
        # (the raw outputs above come straight from the kernel).
        clean_notebook_outputs(notebook)

        # Update execution count
        max_count = 0
        for c in notebook.cells:
            if c.cell_type == 'code' and c.execution_count:
                max_count = max(max_count, c.execution_count)
        cell.execution_count = max_count + 1

        # An execute_result carries the execution count of the cell that produced it.
        for output in cell.outputs:
            if output.get('output_type') == 'execute_result':
                output['execution_count'] = cell.execution_count

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

            # Get notebook_path and kernel_id first
            notebook_path, kernel_id = get_current_notebook_context(notebook_manager)

            # Resolve to absolute path
            if notebook_path and serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)

            # Check if kernel needs to be started
            if kernel_id is None:
                # No kernel available - start a new one on demand
                logger.info("No kernel_id available, starting new kernel for execute_cell")

                # Before starting, we need to determine the correct kernel spec
                target_kernel_name = "python3"  # the default one
                if notebook_path:
                    extracted = await extract_kernelspec_from_notebook(
                        mode, notebook_path, contents_manager, server_client
                    )
                    if extracted and kernel_spec_manager:
                        extracted_name = extracted['name']
                        spec_exists = extracted_name in kernel_spec_manager.find_kernel_specs()
                        if spec_exists:
                            target_kernel_name = extracted_name
                        else:
                            logger.warning(
                                f"Extracted kernel spec '{extracted_name}' from notebook metadata is not installed on this server. "
                                f"Falling back to '{target_kernel_name}'."
                            )

                #kernel_id = await kernel_manager.start_kernel()
                kernel_id = await kernel_manager.start_kernel(kernel_name=target_kernel_name)

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

                if isinstance(cell_source, str):
                    code_to_execute = cell_source
                else:
                    code_to_execute = cell_source.to_py()

                if not code_to_execute or not code_to_execute.strip():
                    return []

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
                raw_outputs: List[dict] = []
                outputs = await execute_via_execution_stack(
                    serverapp=serverapp,
                    kernel_id=kernel_id,
                    code=code_to_execute,
                    timeout=timeout_seconds,
                    raw_outputs=raw_outputs
                )

                # Write outputs back to file
                await self._write_outputs_to_cell(
                    notebook_path, cell_index, outputs, raw_outputs=raw_outputs
                )

                return outputs

        elif mode == ServerMode.MCP_SERVER:
            # Support for ServerMode.MCP_SERVER with kernel specs is implicitly handled in ensure_kernel_alive_fn/create_kernel.
            kernel = ensure_kernel_alive_fn()
            
            await wait_for_kernel_idle(kernel, max_wait_seconds=30)
            current_nb = notebook_manager.get_current_notebook() or "default"
            kid = notebook_manager.get_kernel_id(current_nb) or ""

            async with notebook_manager.get_current_connection() as notebook:
                num_cells = len(notebook)
                if cell_index >= num_cells:
                    raise ValueError(f"Cell index {cell_index} out of range (notebook has {num_cells} cells)")

                cell_source = str(notebook[cell_index].get("source", ""))
                hooks = HookRegistry.get_instance()
                hook_ctx = await hooks.fire(
                    HookEvent.BEFORE_EXECUTE,
                    code=cell_source, kernel_id=kid, metadata={},
                )

                if stream:
                    # Streaming mode: Real-time monitoring with progress updates
                    logger.info(f"Executing cell {cell_index} in streaming mode (timeout: {timeout_seconds}s, interval: {progress_interval}s)")

                    outputs_log = []

                    # Start execution in background
                    execution_task = asyncio.create_task(
                        asyncio.to_thread(notebook.execute_cell, cell_index, kernel)
                    )
                    track_pending_execution(kernel, execution_task)

                    start_time = time.time()
                    last_output_count = 0
                    timed_out = False

                    # Monitor progress
                    while not execution_task.done():
                        elapsed = time.time() - start_time

                        # Check timeout
                        if elapsed > timeout_seconds:
                            execution_task.cancel()
                            timed_out = True
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

                    # Get final result. On timeout the task was cancelled above, so
                    # awaiting it would raise CancelledError, which is a BaseException
                    # and is not caught below, discarding the timeout log just built.
                    if not timed_out:
                        try:
                            await execution_task
                            final_outputs = notebook[cell_index].get("outputs", [])
                            outputs_log.append(f"[COMPLETED in {time.time() - start_time:.1f}s]")

                            # Add any final outputs not captured during monitoring
                            if len(final_outputs) > last_output_count:
                                remaining = final_outputs[last_output_count:]
                                for output in remaining:
                                    extracted = extract_output(output)
                                    if not isinstance(extracted, str):
                                        outputs_log.append(extracted)
                                    elif extracted.strip():
                                        outputs_log.append(extracted)

                        except Exception as e:
                            outputs_log.append(f"[ERROR: {e}]")

                    result = outputs_log if outputs_log else ["[No output generated]"]
                    await hooks.fire(
                        HookEvent.AFTER_EXECUTE,
                        code=cell_source, kernel_id=kid, metadata={},
                        outputs=result, error=None, context=hook_ctx,
                    )
                    return result

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
                        await hooks.fire(
                            HookEvent.AFTER_EXECUTE,
                            code=cell_source, kernel_id=kid, metadata={},
                            outputs=result, error=None, context=hook_ctx,
                        )
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
                            await hooks.fire(
                                HookEvent.AFTER_EXECUTE,
                                code=cell_source, kernel_id=kid, metadata={},
                                outputs=partial_outputs, error=e, context=hook_ctx,
                            )
                            return partial_outputs
                        except Exception:
                            pass

                        timeout_result = [f"[TIMEOUT ERROR: Cell execution exceeded {timeout_seconds} seconds and was interrupted]"]
                        await hooks.fire(
                            HookEvent.AFTER_EXECUTE,
                            code=cell_source, kernel_id=kid, metadata={},
                            outputs=timeout_result, error=e, context=hook_ctx,
                        )
                        return timeout_result

                    except Exception as e:
                        logger.error(f"Error executing cell {cell_index}: {e}")
                        await hooks.fire(
                            HookEvent.AFTER_EXECUTE,
                            code=cell_source, kernel_id=kid, metadata={},
                            outputs=[], error=e, context=hook_ctx,
                        )
                        raise
        else:
            raise ValueError(f"Invalid mode: {mode}")
