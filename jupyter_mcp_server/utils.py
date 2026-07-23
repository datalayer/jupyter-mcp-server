# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

import re
import asyncio
import time
from typing import Any, Optional, Union
from mcp.types import ImageContent
from jupyter_kernel_client import get_mimebundle_text
from jupyter_mcp_server.config import ALLOW_IMG_OUTPUT
from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_nbmodel_client import NotebookModel


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


def resolve_url_and_token_variables(
    jupyter_url,
    jupyter_token,
    document_url,
    document_token,
    runtime_url,
    runtime_token,
) -> tuple[str, str | None, str, str | None]:
    """Resolve merged URL/token settings with per-field precedence."""

    if document_url is not None:
        resolved_document_url = document_url
    elif jupyter_url is not None:
        resolved_document_url = jupyter_url
    else:
        resolved_document_url = "http://localhost:8888"

    if runtime_url is not None:
        resolved_runtime_url = runtime_url
    elif jupyter_url is not None:
        resolved_runtime_url = jupyter_url
    else:
        resolved_runtime_url = "http://localhost:8888"

    resolved_document_token = document_token or jupyter_token
    resolved_runtime_token = runtime_token or jupyter_token

    return (
        resolved_document_url,
        resolved_document_token,
        resolved_runtime_url,
        resolved_runtime_token,
    )


def mcp_auth_headers(mcp_token: str | None) -> dict[str, str]:
    """Build optional bearer auth header for MCP management endpoints."""
    if not mcp_token:
        return {}
    return {"Authorization": f"Bearer {mcp_token}"}


_TRUE_VALUES = frozenset({"1", "true", "t", "yes", "y", "on"})
_FALSE_VALUES = frozenset({"0", "false", "f", "no", "n", "off"})


def parse_bool_option(value, option_name: str) -> bool:
    """Parse a CLI boolean option that accepts explicit True/False values."""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{option_name} expects a boolean value (true/false), got {value!r}."
    )


def do_start(
    transport: str,
    start_new_runtime: bool,
    runtime_url: str,
    runtime_id: str,
    runtime_token: str,
    document_url: str,
    document_id: str,
    document_token: str,
    port: int,
    provider: str,
    jupyterlab: bool,
    open_notebook_in_ui: bool,
    allowed_jupyter_mcp_tools: str,
    otel_file: str = "",
    mcp_token: str = None,
    insecure_mcp_noauth: bool = False,
    reconnect_interval: int = 0,
    execution_timeout: int = 120,
    max_execution_timeout: int = 3600,
):
    """Shared startup routine used by Typer CLI surfaces."""

    import asyncio

    import uvicorn

    from jupyter_mcp_server.config import set_config
    from jupyter_mcp_server.log import logger
    from jupyter_mcp_server.server import __auto_enroll_document, __start_kernel, mcp
    from jupyter_mcp_server.server_context import ServerContext

    if transport == "streamable-http" and not mcp_token and not insecure_mcp_noauth:
        raise ValueError(
            "streamable-http transport requires MCP client authentication. "
            "Set --mcp-token / MCP_TOKEN, or pass --insecure-mcp-noauth to "
            "explicitly allow unauthenticated access."
        )

    logger.info(
        f"Start command received - runtime_url: {repr(runtime_url)}, "
        f"document_url: {repr(document_url)}, provider: {provider}, "
        f"transport: {transport}"
    )

    config = set_config(
        transport=transport,
        provider=provider,
        runtime_url=runtime_url,
        start_new_runtime=start_new_runtime,
        runtime_id=runtime_id,
        runtime_token=runtime_token,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token,
        port=port,
        jupyterlab=jupyterlab,
        open_notebook_in_ui=open_notebook_in_ui,
        allowed_jupyter_mcp_tools=allowed_jupyter_mcp_tools,
        reconnect_interval=reconnect_interval,
        execution_timeout=execution_timeout,
        max_execution_timeout=max_execution_timeout,
    )

    ServerContext.reset()

    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context

        extension_context = get_server_context()
        extension_context.update(
            context_type="MCP_SERVER",
            serverapp=None,
            document_url=config.document_url,
            runtime_url=config.runtime_url,
            jupyterlab=config.jupyterlab,
        )
        logger.info(
            f"Updated jupyter_extension ServerContext with jupyterlab={config.jupyterlab}"
        )
    except Exception as e:
        logger.warning(f"Failed to update jupyter_extension ServerContext: {e}")

    if config.document_id:
        try:
            asyncio.run(__auto_enroll_document())
        except Exception as e:
            logger.error(f"Failed to auto-enroll document '{config.document_id}': {e}")
            if config.start_new_runtime or config.runtime_id:
                try:
                    __start_kernel()
                except Exception as e2:
                    logger.error(f"Failed to start kernel on startup: {e2}")
    elif config.start_new_runtime or config.runtime_id:
        try:
            __start_kernel()
        except Exception as e:
            logger.error(f"Failed to start kernel on startup: {e}")

    from jupyter_mcp_server.otel_hook import maybe_register_otel

    maybe_register_otel(otel_file or None)

    if transport == "streamable-http":
        if mcp_token:
            from jupyter_mcp_server.server import RuntimeTokenVerifier

            mcp._token_verifier = RuntimeTokenVerifier(mcp_token)
            logger.info("MCP endpoint token authentication enabled (using MCP_TOKEN)")
        elif insecure_mcp_noauth:
            logger.warning(
                "MCP endpoint authentication DISABLED (--insecure-mcp-noauth). "
                "Any client can connect without credentials. Not recommended for production."
            )
        else:
            assert False, "early validation should have caught missing MCP auth config"

    logger.info(f"Starting Jupyter MCP Server with transport: {transport}")

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=port)  # noqa: S104
    else:
        raise Exception("Transport should be `stdio` or `streamable-http`.")


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
            

        # Pick the richest readable text from the bundle. For IPython.display.*
        # objects the kernel emits a bundle whose text/plain is only the bare
        # object repr (e.g. "<IPython.core.display.Markdown object>") while the
        # real content lives in a richer key; get_mimebundle_text prefers
        # text/markdown, text/latex, application/json (pretty-printed) over an
        # object-repr text/plain, and falls back to text/plain otherwise. It
        # lives in jupyter-kernel-client so every consumer of the client shares
        # the same selection. Unwrap CRDT YText values to their source first,
        # matching how the other branches here read bundle values.
        text_bundle = {
            mime: str(value.source) if hasattr(value, "source") else value
            for mime, value in data.items()
        }
        rich_text = get_mimebundle_text(text_bundle)
        if rich_text is not None:
            return strip_ansi_codes(rich_text)

        if "text/html" in data:
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


def clean_notebook_outputs(notebook):
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

def format_TSV(headers: list[str], rows: list[list[str]]) -> str:
    """
    Format data as TSV (Tab-Separated Values)
    
    Args:
        headers: The list of headers
        rows: The list of data rows, each row is a list of strings
    
    Returns:
        The formatted TSV string
    """
    if not headers or not rows:
        return "No data to display"
    
    result = []
    
    header_row = "\t".join(headers)
    result.append(header_row)
    
    for row in rows:
        data_row = "\t".join(str(cell) for cell in row)
        result.append(data_row)
    
    return "\n".join(result)

###############################################################################
# Kernel and notebook operation helpers
###############################################################################


def create_kernel(config, logger):
    """Create a new kernel instance using current configuration."""
    from jupyter_kernel_client import KernelClient
    kernel = None
    try:
        # Initialize the kernel client with the provided parameters.
        client_kwargs = {}
        if getattr(config, "reconnect_interval", 0):
            client_kwargs["reconnect_interval"] = config.reconnect_interval
        kernel = KernelClient(
            server_url=config.runtime_url,
            token=config.runtime_token,
            kernel_id=config.runtime_id,
            client_kwargs=client_kwargs if client_kwargs else None,
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


def track_pending_execution(kernel, task):
    """Remember a background execute_cell task on the kernel so is_kernel_busy
    can see it, and forget it once the task actually finishes.

    asyncio.Task.cancel() on a task wrapping asyncio.to_thread() cannot stop the
    underlying OS thread: the thread keeps running notebook.execute_cell() (and
    mutating the shared notebook/kernel state) until it returns on its own,
    regardless of the cancellation request. Recording the task here lets a
    later call see that a previous execution is still in flight instead of
    assuming the kernel is free the moment a timeout is raised.
    """
    kernel._mcp_pending_execution = task

    def _clear(finished_task, kernel=kernel):
        if getattr(kernel, "_mcp_pending_execution", None) is finished_task:
            kernel._mcp_pending_execution = None

    task.add_done_callback(_clear)


# After a timeout + interrupt, the background to_thread work can still mutate
# notebook outputs for a short window. Wait briefly before snapshotting so the
# tool response matches what lands in the notebook (issue #298).
TIMEOUT_OUTPUT_SETTLE_SECONDS = 1.0


async def settle_timed_out_execution(
    execution_task,
    settle_seconds: float = TIMEOUT_OUTPUT_SETTLE_SECONDS,
):
    """Briefly await a still-running background execution before reading outputs.

    Callers should interrupt the kernel first and must not cancel the asyncio
    Task beforehand: cancelling a Task wrapping ``asyncio.to_thread`` marks the
    Task done without stopping the OS thread, which clears
    ``track_pending_execution`` and makes this settle a no-op.

    Uses ``asyncio.shield`` so a settle timeout does not cancel the underlying
    Task either (``wait_for`` would otherwise cancel it and clear the busy flag).
    """
    if execution_task is None or execution_task.done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(execution_task), timeout=settle_seconds)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    except Exception:
        pass


async def emit_execution_progress(
    progress_callback,
    *,
    elapsed: float,
    timeout_seconds: float,
    output_count: int = 0,
    message: str | None = None,
):
    """Invoke an optional progress callback; never let callback errors abort execution."""
    if progress_callback is None:
        return
    try:
        await progress_callback(
            elapsed=elapsed,
            timeout_seconds=timeout_seconds,
            output_count=output_count,
            message=message,
        )
    except Exception as e:
        from jupyter_mcp_server.log import logger
        logger.debug(f"Execution progress callback failed: {e}")


async def execute_cell_with_forced_sync(
    notebook,
    cell_index,
    kernel,
    timeout_seconds=300,
    progress_callback=None,
    progress_interval: int = 5,
):
    """Execute cell with forced real-time synchronization."""
    from jupyter_mcp_server.log import logger

    start_time = time.time()

    # Start execution
    execution_future = asyncio.create_task(
        asyncio.to_thread(notebook.execute_cell, cell_index, kernel)
    )
    track_pending_execution(kernel, execution_future)

    last_output_count = 0
    last_progress_emit = 0.0

    while not execution_future.done():
        elapsed = time.time() - start_time

        if elapsed > timeout_seconds:
            try:
                if hasattr(kernel, 'interrupt'):
                    kernel.interrupt()
            except Exception:
                pass
            # Do not cancel the asyncio Task: cancel completes the wrapper
            # without stopping the OS thread, which clears
            # track_pending_execution early and skips real notebook settles.
            # Interrupt the kernel, briefly wait for the thread, then raise.
            await settle_timed_out_execution(execution_future)
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

        # MCP clients often idle-timeout around a few minutes with no protocol
        # traffic. Emit keepalive progress even when stream=False.
        if (
            progress_interval > 0
            and elapsed > 0
            and (elapsed - last_progress_emit) >= progress_interval
        ):
            last_progress_emit = elapsed
            await emit_execution_progress(
                progress_callback,
                elapsed=elapsed,
                timeout_seconds=timeout_seconds,
                output_count=last_output_count,
            )

        await asyncio.sleep(1)  # Check every second

    # Get final result
    try:
        await execution_future
    except asyncio.CancelledError:
        pass

    return None


def is_kernel_busy(kernel):
    """Check if kernel is currently executing something.

    Reflects the task recorded by track_pending_execution, not
    kernel._client.is_alive(): KernelClient (jupyter_kernel_client) has no
    _client attribute, so that check always fell through to `return False`
    and a timed-out execution's orphaned background thread was never seen
    as "busy" by wait_for_kernel_idle.
    """
    task = getattr(kernel, "_mcp_pending_execution", None)
    return task is not None and not task.done()


async def wait_for_kernel_idle(kernel, max_wait_seconds=60):
    """Wait for kernel to become idle before proceeding."""
    from jupyter_mcp_server.log import logger
    
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
    from jupyter_mcp_server.log import logger
    
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
    logger = None,
    raw_outputs: Optional[list] = None,
    progress_callback=None,
    progress_interval: int = 5,
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
        raw_outputs: Optional list. When provided, the nbformat-shaped outputs
            reported by the kernel are appended to it, so callers that persist
            outputs to disk can keep each output's real ``output_type`` instead
            of re-deriving it from the formatted strings. The formatted return
            value is unaffected.
        progress_callback: Optional async callback for MCP progress/keepalive
        progress_interval: Seconds between progress callback invocations

    Returns:
        List of formatted outputs (strings or ImageContent)
        
    Raises:
        RuntimeError: If jupyter-server-nbmodel extension is not installed
        TimeoutError: If execution exceeds timeout
    """
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
        hook_ctx = await HookRegistry.get_instance().fire(
            HookEvent.BEFORE_EXECUTE,
            code=code, kernel_id=kernel_id, metadata=metadata,
        )
        request_id = execution_stack.put(kernel_id, code, metadata)
        logger.info(f"Execution request {request_id} submitted")

        # Poll for results with proper cleanup on cancellation.
        # If the polling loop is interrupted (e.g. by asyncio.CancelledError
        # from an MCP user-cancel), the request_id would remain orphaned in
        # ExecutionStack, causing subsequent execute_cell calls to hang.
        # The try/except ensures we cancel the kernel execution on any
        # abnormal exit.
        start_time = asyncio.get_event_loop().time()
        last_progress_emit = 0.0
        try:
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
                        error_output = [f"[ERROR: {error_info.get('ename', 'Unknown')}: {error_info.get('evalue', '')}]"]
                        if raw_outputs is not None:
                            raw_outputs.append({
                                "output_type": "error",
                                "ename": error_info.get("ename", "Unknown"),
                                "evalue": error_info.get("evalue", ""),
                                "traceback": error_info.get("traceback", []),
                            })
                        await HookRegistry.get_instance().fire(
                            HookEvent.AFTER_EXECUTE,
                            code=code, kernel_id=kernel_id, metadata=metadata,
                            outputs=error_output, error=error_info, context=hook_ctx,
                        )
                        return error_output

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
                        if raw_outputs is not None:
                            raw_outputs.extend(outputs)
                        logger.info(f"Execution completed with {len(formatted)} formatted outputs: {formatted}")
                    else:
                        formatted = []
                        logger.info("Execution completed with no outputs")
                    await HookRegistry.get_instance().fire(
                        HookEvent.AFTER_EXECUTE,
                        code=code, kernel_id=kernel_id, metadata=metadata,
                        outputs=formatted, error=None, context=hook_ctx,
                    )
                    return formatted if formatted else ["[No output generated]"]

                if (
                    progress_interval > 0
                    and elapsed > 0
                    and (elapsed - last_progress_emit) >= progress_interval
                ):
                    last_progress_emit = elapsed
                    await emit_execution_progress(
                        progress_callback,
                        elapsed=elapsed,
                        timeout_seconds=timeout,
                    )

                # Still pending, wait before next poll
                await asyncio.sleep(poll_interval)

        except (asyncio.CancelledError, TimeoutError):
            # Clean up the orphaned execution request to prevent subsequent
            # execute_cell calls from hanging on stale state.
            logger.warning(
                f"Execution request {request_id} interrupted, "
                f"cancelling kernel {kernel_id} execution"
            )
            try:
                execution_stack.cancel(kernel_id)
            except Exception as cancel_err:
                logger.error(f"Failed to cancel execution on kernel {kernel_id}: {cancel_err}")
            raise

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
        
        # Fire before-execute hook
        hook_ctx = await HookRegistry.get_instance().fire(
            HookEvent.BEFORE_EXECUTE,
            code=code, kernel_id=kernel_id, metadata={},
        )

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
        else:
            result = ["[No output generated]"]

        await HookRegistry.get_instance().fire(
            HookEvent.AFTER_EXECUTE,
            code=code, kernel_id=kernel_id, metadata={},
            outputs=result, error=None, context=hook_ctx,
        )
        return result

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
            clean_notebook_outputs(notebook)
            
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


async def get_jupyter_ydoc(serverapp: Any, file_id: str):
    """Get the YNotebook document if it's currently open in a collaborative session.
    
    This follows the jupyter_ai_tools pattern of accessing YDoc through the
    yroom_manager when the notebook is actively being edited.
    
    Args:
        serverapp: The Jupyter ServerApp instance
        file_id: The file ID for the document
        
    Returns:
        YNotebook instance or None if not in a collaborative session
    """
    try:
        # Access ywebsocket_server from YDocExtension via extension_manager
        # jupyter-collaboration doesn't add yroom_manager to web_app.settings
        ywebsocket_server = None

        if hasattr(serverapp, 'extension_manager'):
            extension_points = serverapp.extension_manager.extension_points
            if 'jupyter_server_ydoc' in extension_points:
                ydoc_ext_point = extension_points['jupyter_server_ydoc']
                if hasattr(ydoc_ext_point, 'app') and ydoc_ext_point.app:
                    ydoc_app = ydoc_ext_point.app
                    if hasattr(ydoc_app, 'ywebsocket_server'):
                        ywebsocket_server = ydoc_app.ywebsocket_server

        if ywebsocket_server is None:
            return None

        room_id = f"json:notebook:{file_id}"

        # Get room and access document via room._document
        # DocumentRoom stores the YNotebook as room._document, not via get_jupyter_ydoc()
        try:
            yroom = await ywebsocket_server.get_room(room_id)
            if yroom and hasattr(yroom, '_document'):
                return yroom._document
        except Exception:
            pass

    except Exception:
        # YDoc not available, will fall back to file operations
        pass

    return None

async def get_notebook_model(serverapp: Any, notebook_path: str):
    """Get the NotebookModel instance if it's currently open in a collaborative session."""
    # Get file_id from file_id_manager
    file_id_manager = serverapp.web_app.settings.get("file_id_manager")
    if file_id_manager is None:
        raise RuntimeError("file_id_manager not available in serverapp")
    
    file_id = file_id_manager.get_id(notebook_path)
    ydoc = await get_jupyter_ydoc(serverapp, file_id)
    if ydoc is None:
        return None
    nb = NotebookModel()
    nb._doc = ydoc
    return nb


def clean_mcp_response_content(content_item):
    """
    Clean MCP response content by filtering out null annotations and meta fields.
    
    Args:
        content_item: Dictionary representing content item (e.g., TextContent)
        
    Returns:
        Cleaned dictionary with null annotations and meta fields removed
    """
    if isinstance(content_item, dict):
        cleaned = content_item.copy()
        
        # Remove annotations and meta fields if they are None/null
        if cleaned.get("annotations") is None:
            cleaned.pop("annotations", None)
        if cleaned.get("meta") is None:
            cleaned.pop("meta", None)
            
        return cleaned
    
    return content_item


def clean_mcp_response(response_dict):
    """
    Clean MCP response by filtering out null annotations and meta fields from all content items.
    
    Args:
        response_dict: Dictionary representing MCP response with content list
        
    Returns:
        Cleaned response dictionary
    """
    if not isinstance(response_dict, dict):
        return response_dict
        
    cleaned_response = response_dict.copy()
    
    if "content" in cleaned_response and isinstance(cleaned_response["content"], list):
        cleaned_content = []
        for item in cleaned_response["content"]:
            cleaned_content.append(clean_mcp_response_content(item))
        cleaned_response["content"] = cleaned_content
    
    return cleaned_response
