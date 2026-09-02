# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unified execute cell tool with configurable streaming."""

import asyncio
import logging
import time
from pathlib import Path

import nbformat
from mcp.types import ImageContent

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.utils import (
    clean_notebook_outputs,
    emit_execution_progress,
    execute_cell_with_forced_sync,
    execute_via_execution_stack,
    get_current_notebook_context,
    get_jupyter_ydoc,
    safe_extract_outputs,
    settle_timed_out_execution,
    track_pending_execution,
    wait_for_code_sandbox_idle,
)

logger = logging.getLogger(__name__)


class ExecuteCellTool(BaseTool):
    """Execute a cell with configurable timeout and optional streaming progress updates"""

    async def _read_notebook_file_with_retry(self, notebook_path: str, retries: int = 4):
        """Read a notebook file, retrying transient parse failures during writes.

        Jupyter can briefly expose an empty or partially-written notebook file
        between write phases; retry a few times before failing.
        """
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with open(notebook_path, encoding="utf-8") as f:
                    return nbformat.read(f, as_version=4)
            except Exception as error:
                last_error = error
                error_text = str(error)
                is_transient_parse_error = (
                    "does not appear to be JSON" in error_text or "Expecting value" in error_text
                )
                if not is_transient_parse_error or attempt >= retries:
                    raise
                backoff = 0.05 * (attempt + 1)
                logger.debug(
                    "Notebook parse failed for %s (attempt %s/%s): %s; retrying in %.2fs",
                    notebook_path,
                    attempt + 1,
                    retries + 1,
                    error,
                    backoff,
                )
                await asyncio.sleep(backoff)

        # Unreachable under normal flow, but keeps typing explicit.
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Unable to read notebook: {notebook_path}")

    @staticmethod
    async def _kernel_exists(kernel_manager, kernel_id: str | None) -> bool:
        """Return whether kernel_id is currently known by the local kernel manager."""
        if not kernel_id:
            return False
        try:
            kernels = kernel_manager.list_kernels()
            if asyncio.iscoroutine(kernels):
                kernels = await kernels
            return any((kernel.get("id") == kernel_id) for kernel in kernels)
        except Exception as error:
            # Fail open: if we cannot introspect kernel list, keep existing behavior.
            logger.debug(f"Unable to check kernel liveness for '{kernel_id}': {error}")
            return True

    async def _start_and_bind_kernel(
        self, kernel_manager, notebook_manager, notebook_path: str | None
    ) -> str:
        """Start a kernel and rebind it to the current notebook in local mode."""
        kernel_id = await kernel_manager.start_kernel(path=notebook_path)
        await asyncio.sleep(1.0)
        logger.info(f"Kernel {kernel_id} started and initialized")

        if notebook_manager is not None:
            kernel_info = {"id": kernel_id}
            # The context lookup resolves the kernel by notebook name, so a
            # path-keyed entry would leave the replaced binding in place.
            name = notebook_manager.get_current_notebook() or notebook_path
            notebook_manager.add_notebook(
                name=name,
                # The parameter is `code_sandbox` since the rename; what is
                # registered here is still a real Jupyter kernel, which is what
                # JUPYTER_SERVER mode executes on.
                code_sandbox=kernel_info,
                server_url="local",
                path=notebook_manager.get_notebook_path(name) or notebook_path,
            )
        return kernel_id

    async def _write_outputs_to_cell(
        self,
        notebook_path: str,
        cell_index: int,
        outputs: list[str | ImageContent],
        raw_outputs: list[dict] | None = None,
        kernel_execution_count: int | None = None,
    ):
        """Write execution outputs back to a notebook cell.

        When raw_outputs is given, the kernel's own nbformat-shaped outputs are
        persisted, which keeps each output's real output_type. Without them only
        the formatted strings are available (the timeout path, for example), and
        the output type can only be guessed from the string form.

        When kernel_execution_count is given, it is used as the cell's
        execution_count directly. Without it, the count is re-derived by
        scanning the notebook's other cells, which diverges from the kernel's
        own counter whenever the two disagree (most commonly after a kernel
        restart mid-session).
        """

        with open(notebook_path, encoding="utf-8") as f:
            notebook = nbformat.read(f, as_version=4)

        # Handle negative indices (e.g., -1 for last cell)
        num_cells = len(notebook.cells)
        if cell_index < 0:
            cell_index = num_cells + cell_index

        if cell_index < 0 or cell_index >= num_cells:
            logger.warning(
                f"Cell index {cell_index} out of range (notebook has {num_cells} cells), cannot write outputs"
            )
            return

        cell = notebook.cells[cell_index]
        if cell.cell_type != "code":
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
                    cell.outputs.append(
                        nbformat.v4.new_output(
                            output_type="display_data",
                            data={output.mime_type: output.data},
                            metadata={},
                        )
                    )
                elif isinstance(output, str):
                    if output == "[No output generated]":
                        # A display-only sentinel for the tool response (see
                        # execute_via_execution_stack in utils.py): a cell that
                        # produced nothing must persist no output, not a
                        # fabricated execute_result.
                        continue
                    if (
                        output.startswith("[ERROR:")
                        or output.startswith("[TIMEOUT ERROR:")
                        or output.startswith("[PROGRESS:")
                    ):
                        cell.outputs.append(
                            nbformat.v4.new_output(output_type="stream", name="stdout", text=output)
                        )
                    else:
                        cell.outputs.append(
                            nbformat.v4.new_output(
                                output_type="execute_result",
                                data={"text/plain": output},
                                metadata={},
                                execution_count=None,
                            )
                        )

        # Strip kernel-protocol fields that are not part of the nbformat schema
        # (the raw outputs above come straight from the kernel).
        clean_notebook_outputs(notebook)

        # Update execution count. Prefer the kernel's own reported count; it is
        # the authoritative source and can diverge from a file-scan heuristic
        # (e.g. after a kernel restart resets the kernel's counter below the
        # notebook's existing max).
        if kernel_execution_count is not None:
            cell.execution_count = kernel_execution_count
        else:
            max_count = 0
            for c in notebook.cells:
                if c.cell_type == "code" and c.execution_count:
                    max_count = max(max_count, c.execution_count)
            cell.execution_count = max_count + 1

        # An execute_result carries the execution count of the cell that produced it.
        for output in cell.outputs:
            if output.get("output_type") == "execute_result":
                output["execution_count"] = cell.execution_count

        with open(notebook_path, "w", encoding="utf-8") as f:
            nbformat.write(notebook, f)

        logger.info(f"Wrote {len(outputs)} outputs to cell {cell_index} in {notebook_path}")

    async def execute(
        self,
        mode: ServerMode,
        sandbox_server_client=None,
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
        ensure_code_sandbox_alive_fn=None,
        progress_callback=None,
        **kwargs,
    ) -> list[str | ImageContent]:
        """Execute a cell with configurable timeout and optional streaming progress updates.

        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            serverapp: ServerApp instance for JUPYTER_SERVER mode
            kernel_manager: Kernel manager for JUPYTER_SERVER mode
            notebook_manager: Notebook manager for MCP_SERVER mode
            cell_index: Index of the cell to execute (0-based)
            timeout_seconds: Maximum seconds to wait for execution
            stream: Enable streaming progress updates for long-running cells
            progress_interval: Seconds between progress updates (MCP keepalive + stream log)
            ensure_code_sandbox_alive_fn: Function to ensure kernel is alive (MCP_SERVER)
            progress_callback: Optional async callback for MCP progress/keepalive

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

            # Preserve the root-relative API path for kernel creation, then resolve
            # a separate filesystem path for file and YDoc operations below.
            notebook_path, kernel_id = get_current_notebook_context(notebook_manager)
            notebook_api_path = notebook_path

            # Resolve to absolute path
            if notebook_path and serverapp and not Path(notebook_path).is_absolute():
                root_dir = serverapp.root_dir
                notebook_path = str(Path(root_dir) / notebook_path)

            # Start or rebind when notebook context has no kernel, or points to
            # a stale/cullled kernel id.
            if kernel_id is None:
                logger.info("No kernel_id available, starting new kernel for execute_cell")
                kernel_id = await self._start_and_bind_kernel(
                    kernel_manager, notebook_manager, notebook_api_path
                )
            elif not await self._kernel_exists(kernel_manager, kernel_id):
                logger.info(
                    "Kernel %s is not available anymore, starting a replacement for execute_cell",
                    kernel_id,
                )
                kernel_id = await self._start_and_bind_kernel(
                    kernel_manager, notebook_manager, notebook_api_path
                )

            logger.info(
                f"Executing cell {cell_index} in JUPYTER_SERVER mode (timeout: {timeout_seconds}s)"
            )

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
                    raise ValueError(
                        f"Cell index {cell_index} out of range (notebook has {num_cells} cells)"
                    )

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
                try:
                    outputs = await execute_via_execution_stack(
                        serverapp=serverapp,
                        kernel_id=kernel_id,
                        code=code_to_execute,
                        document_id=document_id,
                        cell_id=cell_id,
                        timeout=timeout_seconds,
                        progress_callback=progress_callback,
                        progress_interval=progress_interval,
                    )
                except Exception as error:
                    error_text = str(error).lower()
                    if "kernel" in error_text and "not found" in error_text:
                        logger.warning(
                            "Kernel %s disappeared during execute_cell; starting replacement and retrying once",
                            kernel_id,
                        )
                        kernel_id = await self._start_and_bind_kernel(
                            kernel_manager, notebook_manager, notebook_api_path
                        )
                        outputs = await execute_via_execution_stack(
                            serverapp=serverapp,
                            kernel_id=kernel_id,
                            code=code_to_execute,
                            document_id=document_id,
                            cell_id=cell_id,
                            timeout=timeout_seconds,
                            progress_callback=progress_callback,
                            progress_interval=progress_interval,
                        )
                    else:
                        raise

                return outputs
            else:
                # Notebook not open - use file-based approach
                logger.info(f"Notebook {file_id} not open, using file mode")

                notebook = await self._read_notebook_file_with_retry(notebook_path)

                num_cells = len(notebook.cells)
                if cell_index >= num_cells:
                    raise ValueError(
                        f"Cell index {cell_index} out of range (notebook has {num_cells} cells)"
                    )

                cell = notebook.cells[cell_index]
                if cell.cell_type != "code":
                    raise ValueError(f"Cell {cell_index} is not a code cell")

                code_to_execute = cell.source
                if not code_to_execute.strip():
                    return []

                # Execute without RTC metadata
                raw_outputs: list[dict] = []
                execution_count_out: list[int] = []
                try:
                    outputs = await execute_via_execution_stack(
                        serverapp=serverapp,
                        kernel_id=kernel_id,
                        code=code_to_execute,
                        timeout=timeout_seconds,
                        raw_outputs=raw_outputs,
                        execution_count_out=execution_count_out,
                        progress_callback=progress_callback,
                        progress_interval=progress_interval,
                    )
                except Exception as error:
                    error_text = str(error).lower()
                    if "kernel" in error_text and "not found" in error_text:
                        logger.warning(
                            "Kernel %s disappeared during execute_cell; starting replacement and retrying once",
                            kernel_id,
                        )
                        kernel_id = await self._start_and_bind_kernel(
                            kernel_manager, notebook_manager, notebook_api_path
                        )
                        raw_outputs = []
                        execution_count_out = []
                        outputs = await execute_via_execution_stack(
                            serverapp=serverapp,
                            kernel_id=kernel_id,
                            code=code_to_execute,
                            timeout=timeout_seconds,
                            raw_outputs=raw_outputs,
                            execution_count_out=execution_count_out,
                            progress_callback=progress_callback,
                            progress_interval=progress_interval,
                        )
                    else:
                        raise

                # Write outputs back to file
                await self._write_outputs_to_cell(
                    notebook_path,
                    cell_index,
                    outputs,
                    raw_outputs=raw_outputs,
                    kernel_execution_count=execution_count_out[0] if execution_count_out else None,
                )

                return outputs

        elif mode == ServerMode.MCP_SERVER:
            kernel = ensure_code_sandbox_alive_fn()
            await wait_for_code_sandbox_idle(kernel, max_wait_seconds=30)
            current_nb = notebook_manager.get_current_notebook() or "default"
            kid = notebook_manager.get_code_sandbox_id(current_nb) or ""

            async with notebook_manager.get_current_connection() as notebook:
                num_cells = len(notebook)
                if cell_index >= num_cells:
                    raise ValueError(
                        f"Cell index {cell_index} out of range (notebook has {num_cells} cells)"
                    )

                cell_source = str(notebook[cell_index].get("source", ""))
                hooks = HookRegistry.get_instance()
                hook_ctx = await hooks.fire(
                    HookEvent.BEFORE_EXECUTE,
                    code=cell_source,
                    kernel_id=kid,
                    metadata={},
                )

                if stream:
                    # Streaming mode: Real-time monitoring with progress updates
                    logger.info(
                        f"Executing cell {cell_index} in streaming mode (timeout: {timeout_seconds}s, interval: {progress_interval}s)"
                    )

                    # Streaming only adds a timeline; the cell's own outputs are
                    # snapshotted at the end so the response keeps the same shape
                    # as the non-streaming path (structured outputs first, in
                    # kernel order), with these log lines appended after them.
                    timeline: list[str] = []

                    # Start execution in background. The sandbox client emits
                    # Jupyter-shaped output-hook messages and reply envelopes
                    # directly, so the notebook model can consume it as-is.
                    execution_task = asyncio.create_task(
                        asyncio.to_thread(
                            notebook.execute_cell, cell_index, kernel
                        )
                    )
                    track_pending_execution(kernel, execution_task)

                    # perf_counter: high-res and monotonic. time.time() on Windows
                    # (esp. older CPython) can return the same value twice, so
                    # elapsed stays 0 and ``elapsed > 0`` misses an immediate
                    # timeout; the 1s poll then lets a short cell finish as
                    # COMPLETED instead of TIMEOUT (CI: windows-latest, 3.10).
                    start_time = time.perf_counter()
                    last_output_count = 0
                    last_progress_emit = 0.0
                    timed_out = False

                    # How to stop the cell, as opposed to stopping the wait
                    # for it. This is the *streaming* loop — the documented
                    # mode for long-running cells, and so the one most likely
                    # to be cancelled — and it had neither hook while the
                    # non-streaming loop in `utils` had both.
                    try:
                        from jupyter_mcp_server.tasks import register_interrupt

                        await register_interrupt(kernel.interrupt)
                    except Exception as error:  # noqa: BLE001 - never in the way
                        logger.debug("The interrupt could not be registered: %s", error)

                    # Monitor progress
                    while not execution_task.done():
                        elapsed = time.perf_counter() - start_time

                        # >= so timeout_seconds=0 means immediate timeout even
                        # when elapsed is still 0.0 on a coarse clock tick.
                        if elapsed >= timeout_seconds:
                            timed_out = True
                            timeline.append(f"[TIMEOUT at {elapsed:.1f}s: Interrupting execution]")
                            try:
                                kernel.interrupt()
                                timeline.append("[Sent interrupt signal to kernel]")
                            except Exception:
                                pass
                            # Do not cancel execution_task: see settle_timed_out_execution.
                            break

                        # Record when new outputs appear. Only the arrival is
                        # logged: copying the payload here would duplicate it,
                        # and re-formatting it as a string would drop images.
                        try:
                            current_outputs = notebook[cell_index].get("outputs", [])
                            if len(current_outputs) > last_output_count:
                                new_count = len(current_outputs) - last_output_count
                                last_output_count = len(current_outputs)
                                timeline.append(
                                    f"[{elapsed:.1f}s] {new_count} new output(s), "
                                    f"{last_output_count} total"
                                )
                                # Into the task, where a reader can see them.
                                # A cell cancelled at minute nine of ten has
                                # no result and may have printed five hundred
                                # lines.
                                try:
                                    from jupyter_mcp_server.tasks import record_output

                                    await record_output(
                                        safe_extract_outputs(current_outputs)
                                    )
                                except Exception as error:  # noqa: BLE001
                                    logger.debug(
                                        "Progress could not be recorded: %s", error
                                    )

                        except Exception as e:
                            timeline.append(f"[{elapsed:.1f}s] Error checking outputs: {e}")

                        # Progress update (tool log + MCP keepalive). Use wall-clock
                        # gating so we emit once per interval, not on every poll
                        # where int(elapsed) % interval happens to be 0.
                        if (
                            progress_interval > 0
                            and elapsed > 0
                            and (elapsed - last_progress_emit) >= progress_interval
                        ):
                            last_progress_emit = elapsed
                            timeline.append(
                                f"[PROGRESS: {elapsed:.1f}s elapsed, {last_output_count} outputs so far]"
                            )
                            await emit_execution_progress(
                                progress_callback,
                                elapsed=elapsed,
                                timeout_seconds=timeout_seconds,
                                output_count=last_output_count,
                            )

                        # Do not sleep past the remaining timeout budget (short
                        # timeouts used to wait a full second before re-check).
                        remaining = timeout_seconds - elapsed
                        await asyncio.sleep(min(1.0, max(remaining, 0.0)))

                    # Wait for the execution to settle before snapshotting. On
                    # timeout the task is not cancelled (see
                    # settle_timed_out_execution), so awaiting it directly would
                    # block for the full cell.
                    if timed_out:
                        await settle_timed_out_execution(execution_task)
                    else:
                        try:
                            await execution_task
                            timeline.append(
                                f"[COMPLETED in {time.perf_counter() - start_time:.1f}s]"
                            )
                        except Exception as e:
                            timeline.append(f"[ERROR: {e}]")

                    # Same extraction as the non-streaming path, so streaming
                    # does not change the outputs a client receives.
                    try:
                        outputs = safe_extract_outputs(notebook[cell_index].get("outputs", []))
                    except Exception as e:
                        outputs = []
                        timeline.append(f"[ERROR reading outputs: {e}]")

                    result = (outputs + timeline) or ["[No output generated]"]
                    await hooks.fire(
                        HookEvent.AFTER_EXECUTE,
                        code=cell_source,
                        kernel_id=kid,
                        metadata={},
                        outputs=result,
                        error=None,
                        context=hook_ctx,
                    )
                    return result

                else:
                    # Non-streaming mode: Use forced synchronization
                    logger.info(
                        f"Starting execution of cell {cell_index} with {timeout_seconds}s timeout"
                    )

                    try:
                        # Use the forced sync function
                        await execute_cell_with_forced_sync(
                            notebook,
                            cell_index,
                            kernel,
                            timeout_seconds,
                            progress_callback=progress_callback,
                            progress_interval=progress_interval,
                        )

                        # Get final outputs
                        outputs = notebook[cell_index].get("outputs", [])
                        result = safe_extract_outputs(outputs)

                        logger.info(
                            f"Cell {cell_index} completed successfully with {len(result)} outputs"
                        )
                        await hooks.fire(
                            HookEvent.AFTER_EXECUTE,
                            code=cell_source,
                            kernel_id=kid,
                            metadata={},
                            outputs=result,
                            error=None,
                            context=hook_ctx,
                        )
                        return result

                    except asyncio.TimeoutError as e:
                        logger.error(f"Cell {cell_index} execution timed out: {e}")
                        # execute_cell_with_forced_sync already interrupted the
                        # kernel and awaited the settle window before raising.
                        # Repeating either here interrupts the kernel twice and
                        # doubles the time the tool call takes to return.

                        # Return partial outputs if available
                        try:
                            outputs = notebook[cell_index].get("outputs", [])
                            partial_outputs = safe_extract_outputs(outputs)
                            partial_outputs.append(
                                f"[TIMEOUT ERROR: Execution exceeded {timeout_seconds} seconds]"
                            )
                            await hooks.fire(
                                HookEvent.AFTER_EXECUTE,
                                code=cell_source,
                                kernel_id=kid,
                                metadata={},
                                outputs=partial_outputs,
                                error=e,
                                context=hook_ctx,
                            )
                            return partial_outputs
                        except Exception:
                            pass

                        timeout_result = [
                            f"[TIMEOUT ERROR: Cell execution exceeded {timeout_seconds} seconds and was interrupted]"
                        ]
                        await hooks.fire(
                            HookEvent.AFTER_EXECUTE,
                            code=cell_source,
                            kernel_id=kid,
                            metadata={},
                            outputs=timeout_result,
                            error=e,
                            context=hook_ctx,
                        )
                        return timeout_result

                    except Exception as e:
                        logger.error(f"Error executing cell {cell_index}: {e}")
                        await hooks.fire(
                            HookEvent.AFTER_EXECUTE,
                            code=cell_source,
                            kernel_id=kid,
                            metadata={},
                            outputs=[],
                            error=e,
                            context=hook_ctx,
                        )
                        raise
        else:
            raise ValueError(f"Invalid mode: {mode}")
