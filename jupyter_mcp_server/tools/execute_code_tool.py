# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute IPython code directly in kernel tool."""

import asyncio
import logging
from typing import cast

from code_sandboxes import CodeSandboxClient
from jupyter_server_client import JupyterServerClient
from mcp.types import ImageContent

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.utils import (
    emit_execution_progress,
    settle_timed_out_execution,
    track_pending_execution,
)

logger = logging.getLogger(__name__)


class ExecuteCodeTool(BaseTool):
    """Execute code directly in a kernel.

    Defaults to the current active notebook's kernel; pass kernel_id to target
    a specific kernel, including raw kernels with no notebook attached.
    """

    async def _execute_via_kernel_manager(
        self, kernel_manager, kernel_id: str, code: str, timeout: int, safe_extract_outputs_fn
    ) -> list[str | ImageContent]:
        """Execute code using kernel_manager (JUPYTER_SERVER mode).

        Uses execute_code_local which handles ZMQ message collection properly.
        """
        from jupyter_mcp_server.utils import execute_code_local

        # Get serverapp from kernel_manager
        serverapp = kernel_manager.parent

        # Use centralized execute_code_local function
        return await execute_code_local(
            serverapp=serverapp,
            notebook_path="",  # Not needed for execute_code
            code=code,
            kernel_id=kernel_id,
            timeout=timeout,
            logger=logger,
        )

    def _connect_to_kernel(
        self, kernel_id: str, sandbox_server_client: JupyterServerClient | None
    ) -> tuple[CodeSandboxClient | None, str | None]:
        """Connect to an existing kernel by ID (MCP_SERVER mode).

        Returns (kernel, None) on success, or (None, error_message) if the id
        does not name a kernel on the server.
        """
        from jupyter_mcp_server.config import get_config
        from jupyter_mcp_server.sandbox_client import create_jupyter_sandbox_client
        from jupyter_mcp_server.server_context import ServerContext

        if sandbox_server_client is not None:
            kernels = sandbox_server_client.kernels.list_kernels()
            if not any(kernel.id == kernel_id for kernel in kernels):
                return None, (
                    f"[ERROR: Kernel '{kernel_id}' not found in jupyter server, please check "
                    f"whether the kernel already exists using 'list_kernels' tool.]"
                )

        config = get_config()
        # Password auth carries credentials via cookie/XSRF headers; when present,
        # drop the token so it can't override them (mirrors create_kernel and
        # use_notebook). Without this, a borrowed cross-kernel connection under
        # password auth would be unauthenticated, since code_sandbox_token is typically
        # None in that mode.
        auth_headers = ServerContext.get_instance().code_sandbox_auth_headers
        code_sandbox_client = create_jupyter_sandbox_client(
            server_url=config.code_sandbox_url,
            token=None if auth_headers else config.code_sandbox_token,
            kernel_id=kernel_id,
            timeout=getattr(config, "execution_timeout", None),
            reconnect_interval=getattr(config, "reconnect_interval", 0) or 0,
            headers=auth_headers or None,
            logger=logger,
        )
        return cast(CodeSandboxClient, code_sandbox_client), None

    async def _execute_via_notebook_manager(
        self,
        notebook_manager: NotebookManager,
        code: str,
        timeout: int,
        ensure_kernel_alive_fn,
        wait_for_kernel_idle_fn,
        safe_extract_outputs_fn,
        kernel_id: str = None,
        sandbox_server_client=None,
        progress_callback=None,
        progress_interval: int = 5,
    ) -> list[str | ImageContent]:
        """Execute code using notebook_manager (MCP_SERVER mode - original logic).

        When kernel_id names a kernel other than the current notebook's, the code
        runs in that kernel instead. Such a connection is opened for this call only
        and closed afterwards without shutting the kernel down.
        """
        # Get current notebook name and kernel
        current_notebook = notebook_manager.get_current_notebook() or "default"
        current_kernel_id = notebook_manager.get_kernel_id(current_notebook)

        # A sandbox client we connect to here is borrowed, not owned: it must be released
        # in the finally below, and never shut down.
        borrowed_sandbox: CodeSandboxClient | None = None
        if kernel_id is not None and kernel_id != current_kernel_id:
            code_sandbox_client, error = self._connect_to_kernel(kernel_id, sandbox_server_client)
            if error is not None:
                return [error]
            if code_sandbox_client is None:
                return ["[ERROR: Failed to connect to kernel]"]
            borrowed_sandbox = code_sandbox_client
            kid = kernel_id
        else:
            code_sandbox_client = notebook_manager.get_kernel(current_notebook)

            if not code_sandbox_client:
                # Ensure kernel is alive
                code_sandbox_client = ensure_kernel_alive_fn()

            if isinstance(code_sandbox_client, dict):
                return [
                    "[ERROR: Kernel metadata found instead of an active CodeSandboxClient in MCP_SERVER mode]"
                ]

            kid = current_kernel_id or ""

        try:
            return await self._execute_on_kernel(
                code_sandbox_client=code_sandbox_client,
                kid=kid,
                code=code,
                timeout=timeout,
                wait_for_kernel_idle_fn=wait_for_kernel_idle_fn,
                safe_extract_outputs_fn=safe_extract_outputs_fn,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )
        finally:
            if borrowed_sandbox is not None:
                pending = getattr(borrowed_sandbox, "_mcp_pending_execution", None)
                if pending is not None and not pending.done():
                    # track_pending_execution's background thread is still using this
                    # client's transport; releasing now would close it out from under
                    # that thread, so defer until the thread actually finishes.
                    def _release_when_done(_task, sandbox=borrowed_sandbox, kid=kid):
                        self._release_borrowed_kernel(sandbox, kid)

                    pending.add_done_callback(_release_when_done)
                else:
                    self._release_borrowed_kernel(borrowed_sandbox, kid)

    def _release_borrowed_kernel(self, code_sandbox_client: CodeSandboxClient, kid: str) -> None:
        """Stop a borrowed kernel connection without shutting the kernel down."""
        try:
            code_sandbox_client.stop(shutdown_kernel=False)
        except Exception as stop_err:
            logger.warning(f"Failed to release kernel {kid}: {stop_err}")

    async def _execute_on_kernel(
        self,
        code_sandbox_client: CodeSandboxClient,
        kid: str,
        code: str,
        timeout: int,
        wait_for_kernel_idle_fn,
        safe_extract_outputs_fn,
        progress_callback=None,
        progress_interval: int = 5,
    ) -> list[str | ImageContent]:
        """Run code on an already-resolved sandbox client (MCP_SERVER mode)."""
        # Wait for kernel to be idle before executing
        await wait_for_kernel_idle_fn(code_sandbox_client, max_wait_seconds=30)

        logger.info(f"Executing IPython code (MCP_SERVER) with timeout {timeout}s: {code[:100]}...")

        hooks = HookRegistry.get_instance()
        hook_ctx = await hooks.fire(
            HookEvent.BEFORE_EXECUTE,
            code=code,
            kernel_id=kid,
            metadata={},
        )

        try:
            execution_task = asyncio.create_task(
                asyncio.to_thread(code_sandbox_client.execute, code)
            )
            track_pending_execution(code_sandbox_client, execution_task)

            start_time = asyncio.get_event_loop().time()
            last_progress_emit = 0.0

            # Wait for execution with timeout, emitting MCP keepalive progress
            # so clients do not idle-timeout on long-running cells.
            # Use >= so timeout=0 is an immediate timeout even if elapsed is 0.
            while not execution_task.done():
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    try:
                        if code_sandbox_client and hasattr(code_sandbox_client, "interrupt"):
                            code_sandbox_client.interrupt()
                            logger.info("Sent interrupt signal to kernel due to timeout")
                    except Exception as interrupt_err:
                        logger.error(f"Failed to interrupt kernel: {interrupt_err}")
                    # Do not cancel execution_task: see settle_timed_out_execution.
                    await settle_timed_out_execution(execution_task)
                    result = [
                        f"[TIMEOUT ERROR: IPython execution exceeded {timeout} seconds and was interrupted]"
                    ]
                    await hooks.fire(
                        HookEvent.AFTER_EXECUTE,
                        code=code,
                        kernel_id=kid,
                        metadata={},
                        outputs=result,
                        error=asyncio.TimeoutError(),
                        context=hook_ctx,
                    )
                    return result

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

                remaining = timeout - elapsed
                poll = min(1.0, max(0.05, progress_interval / 5 if progress_interval else 1.0))
                await asyncio.sleep(min(poll, max(remaining, 0.0)))

            outputs = execution_task.result()

            # Process and extract outputs
            if outputs:
                result = safe_extract_outputs_fn(outputs["outputs"])
                logger.info(f"IPython execution completed successfully with {len(result)} outputs")
            else:
                result = ["[No output generated]"]

            await hooks.fire(
                HookEvent.AFTER_EXECUTE,
                code=code,
                kernel_id=kid,
                metadata={},
                outputs=result,
                error=None,
                context=hook_ctx,
            )
            return result

        except Exception as e:
            logger.error(f"Error executing IPython code: {e}")
            await hooks.fire(
                HookEvent.AFTER_EXECUTE,
                code=code,
                kernel_id=kid,
                metadata={},
                outputs=[],
                error=e,
                context=hook_ctx,
            )
            return [f"[ERROR: {e!s}]"]

    async def execute(
        self,
        mode: ServerMode,
        sandbox_server_client=None,
        contents_manager=None,
        kernel_manager=None,
        kernel_spec_manager=None,
        notebook_manager=None,
        # Tool-specific parameters
        code: str = None,
        timeout: int = 60,
        kernel_id: str = None,
        ensure_kernel_alive_fn=None,
        wait_for_kernel_idle_fn=None,
        safe_extract_outputs_fn=None,
        progress_callback=None,
        progress_interval: int = 5,
        **kwargs,
    ) -> list[str | ImageContent]:
        """Execute IPython code directly in the kernel.

        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            sandbox_server_client: JupyterServerClient (used to resolve kernel_id in
                MCP_SERVER mode)
            contents_manager: Contents manager (not used)
            kernel_manager: Kernel manager (for JUPYTER_SERVER mode)
            kernel_spec_manager: Kernel spec manager (not used)
            notebook_manager: Notebook manager (for MCP_SERVER mode)
            code: IPython code to execute (supports magic commands, shell commands with !, and Python code)
            timeout: Execution timeout in seconds (default: 60s)
            kernel_id: Kernel to execute in; defaults to the current notebook's kernel
            ensure_kernel_alive_fn: Function to ensure kernel is alive (for MCP_SERVER mode)
            wait_for_kernel_idle_fn: Function to wait for kernel idle state (for MCP_SERVER mode)
            safe_extract_outputs_fn: Function to safely extract outputs
            progress_callback: Optional async callback for MCP progress/keepalive
            progress_interval: Seconds between progress callback invocations

        Returns:
            List of outputs from the executed code
        """
        if safe_extract_outputs_fn is None:
            raise ValueError("safe_extract_outputs_fn is required")

        # JUPYTER_SERVER mode: Use kernel_manager directly
        if mode == ServerMode.JUPYTER_SERVER and kernel_manager is not None:
            if kernel_id is None:
                # Try to get kernel_id from context
                from jupyter_mcp_server.utils import get_current_notebook_context

                _, kernel_id = get_current_notebook_context(notebook_manager)

            if kernel_id is None:
                # No kernel available - start a new one on demand
                logger.info("No kernel_id available, starting new kernel for execute_code")
                kernel_id = await kernel_manager.start_kernel()

                # Store the kernel in notebook_manager if available
                if notebook_manager is not None:
                    default_notebook = "default"
                    kernel_info = {"id": kernel_id}
                    notebook_manager.add_notebook(
                        default_notebook,
                        kernel_info,
                        server_url="local",
                        token=None,
                        path="notebook.ipynb",  # Placeholder path
                    )
                    notebook_manager.set_current_notebook(default_notebook)

            logger.info(f"Executing IPython in JUPYTER_SERVER mode with kernel_id={kernel_id}")
            return await self._execute_via_kernel_manager(
                kernel_manager=kernel_manager,
                kernel_id=kernel_id,
                code=code,
                timeout=timeout,
                safe_extract_outputs_fn=safe_extract_outputs_fn,
            )

        # MCP_SERVER mode: Use notebook_manager (original behavior)
        elif mode == ServerMode.MCP_SERVER and notebook_manager is not None:
            if ensure_kernel_alive_fn is None:
                raise ValueError("ensure_kernel_alive_fn is required for MCP_SERVER mode")
            if wait_for_kernel_idle_fn is None:
                raise ValueError("wait_for_kernel_idle_fn is required for MCP_SERVER mode")

            logger.info(f"Executing IPython in MCP_SERVER mode with kernel_id={kernel_id}")
            return await self._execute_via_notebook_manager(
                notebook_manager=notebook_manager,
                code=code,
                timeout=timeout,
                ensure_kernel_alive_fn=ensure_kernel_alive_fn,
                wait_for_kernel_idle_fn=wait_for_kernel_idle_fn,
                safe_extract_outputs_fn=safe_extract_outputs_fn,
                kernel_id=kernel_id,
                sandbox_server_client=sandbox_server_client,
                progress_callback=progress_callback,
                progress_interval=progress_interval,
            )

        else:
            return ["[ERROR: Invalid mode or missing required managers]"]
