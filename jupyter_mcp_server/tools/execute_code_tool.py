# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute IPython code directly in kernel tool."""

import asyncio
import logging
from typing import Union

from mcp.types import ImageContent

from jupyter_mcp_server.hooks import HookEvent, HookRegistry
from jupyter_mcp_server.tools._base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager

logger = logging.getLogger(__name__)


class ExecuteCodeTool(BaseTool):
    """Execute code directly in a kernel.

    Defaults to the current active notebook's kernel; pass kernel_id to target
    a specific kernel, including raw kernels with no notebook attached.
    """
    
    async def _execute_via_kernel_manager(
        self,
        kernel_manager,
        kernel_id: str,
        code: str,
        timeout: int,
        safe_extract_outputs_fn
    ) -> list[Union[str, ImageContent]]:
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
            logger=logger
        )
    
    def _connect_to_kernel(self, kernel_id: str, server_client):
        """Connect to an existing kernel by ID (MCP_SERVER mode).

        Returns (kernel, None) on success, or (None, error_message) if the id
        does not name a kernel on the server.
        """
        from jupyter_kernel_client import KernelClient

        from jupyter_mcp_server.config import get_config
        from jupyter_mcp_server.server_context import ServerContext

        if server_client is not None:
            kernels = server_client.kernels.list_kernels()
            if not any(kernel.id == kernel_id for kernel in kernels):
                return None, (
                    f"[ERROR: Kernel '{kernel_id}' not found in jupyter server, please check "
                    f"whether the kernel already exists using 'list_kernels' tool.]"
                )

        config = get_config()
        # Password auth carries credentials via cookie/XSRF headers; when present,
        # drop the token so it can't override them (mirrors create_kernel and
        # use_notebook). Without this, a borrowed cross-kernel connection under
        # password auth would be unauthenticated, since runtime_token is typically
        # None in that mode.
        auth_headers = ServerContext.get_instance().runtime_auth_headers
        kernel_kwargs = {
            "server_url": config.runtime_url,
            "token": None if auth_headers else config.runtime_token,
            "kernel_id": kernel_id,
        }
        if auth_headers:
            kernel_kwargs["headers"] = auth_headers
        kernel = KernelClient(**kernel_kwargs)
        kernel.start()
        return kernel, None

    async def _execute_via_notebook_manager(
        self,
        notebook_manager: NotebookManager,
        code: str,
        timeout: int,
        ensure_kernel_alive_fn,
        wait_for_kernel_idle_fn,
        safe_extract_outputs_fn,
        kernel_id: str = None,
        server_client=None
    ) -> list[Union[str, ImageContent]]:
        """Execute code using notebook_manager (MCP_SERVER mode - original logic).

        When kernel_id names a kernel other than the current notebook's, the code
        runs in that kernel instead. Such a connection is opened for this call only
        and closed afterwards without shutting the kernel down.
        """
        # Get current notebook name and kernel
        current_notebook = notebook_manager.get_current_notebook() or "default"
        current_kernel_id = notebook_manager.get_kernel_id(current_notebook)

        # A kernel we connect to here is borrowed, not owned: it must be released
        # in the finally below, and never shut down.
        borrowed_kernel = None
        if kernel_id is not None and kernel_id != current_kernel_id:
            kernel, error = self._connect_to_kernel(kernel_id, server_client)
            if error is not None:
                return [error]
            borrowed_kernel = kernel
            kid = kernel_id
        else:
            kernel = notebook_manager.get_kernel(current_notebook)

            if not kernel:
                # Ensure kernel is alive
                kernel = ensure_kernel_alive_fn()

            kid = current_kernel_id or ""

        try:
            return await self._execute_on_kernel(
                kernel=kernel,
                kid=kid,
                code=code,
                timeout=timeout,
                wait_for_kernel_idle_fn=wait_for_kernel_idle_fn,
                safe_extract_outputs_fn=safe_extract_outputs_fn,
            )
        finally:
            if borrowed_kernel is not None:
                try:
                    borrowed_kernel.stop(shutdown_kernel=False)
                except Exception as stop_err:
                    logger.warning(f"Failed to release kernel {kid}: {stop_err}")

    async def _execute_on_kernel(
        self,
        kernel,
        kid: str,
        code: str,
        timeout: int,
        wait_for_kernel_idle_fn,
        safe_extract_outputs_fn
    ) -> list[Union[str, ImageContent]]:
        """Run code on an already-resolved kernel (MCP_SERVER mode)."""
        # Wait for kernel to be idle before executing
        await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)

        logger.info(f"Executing IPython code (MCP_SERVER) with timeout {timeout}s: {code[:100]}...")

        hooks = HookRegistry.get_instance()
        hook_ctx = await hooks.fire(
            HookEvent.BEFORE_EXECUTE,
            code=code, kernel_id=kid, metadata={},
        )

        try:
            # Execute code directly with kernel
            execution_task = asyncio.create_task(
                asyncio.to_thread(kernel.execute, code)
            )

            # Wait for execution with timeout
            try:
                outputs = await asyncio.wait_for(execution_task, timeout=timeout)
            except asyncio.TimeoutError as e:
                execution_task.cancel()
                try:
                    if kernel and hasattr(kernel, 'interrupt'):
                        kernel.interrupt()
                        logger.info("Sent interrupt signal to kernel due to timeout")
                except Exception as interrupt_err:
                    logger.error(f"Failed to interrupt kernel: {interrupt_err}")

                result = [f"[TIMEOUT ERROR: IPython execution exceeded {timeout} seconds and was interrupted]"]
                await hooks.fire(
                    HookEvent.AFTER_EXECUTE,
                    code=code, kernel_id=kid, metadata={},
                    outputs=result, error=e, context=hook_ctx,
                )
                return result

            # Process and extract outputs
            if outputs:
                result = safe_extract_outputs_fn(outputs['outputs'])
                logger.info(f"IPython execution completed successfully with {len(result)} outputs")
            else:
                result = ["[No output generated]"]

            await hooks.fire(
                HookEvent.AFTER_EXECUTE,
                code=code, kernel_id=kid, metadata={},
                outputs=result, error=None, context=hook_ctx,
            )
            return result

        except Exception as e:
            logger.error(f"Error executing IPython code: {e}")
            await hooks.fire(
                HookEvent.AFTER_EXECUTE,
                code=code, kernel_id=kid, metadata={},
                outputs=[], error=e, context=hook_ctx,
            )
            return [f"[ERROR: {str(e)}]"]
    
    async def execute(
        self,
        mode: ServerMode,
        server_client=None,
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
        **kwargs
    ) -> list[Union[str, ImageContent]]:
        """Execute IPython code directly in the kernel.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: JupyterServerClient (used to resolve kernel_id in MCP_SERVER mode)
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
                        path="notebook.ipynb"  # Placeholder path
                    )
                    notebook_manager.set_current_notebook(default_notebook)
            
            logger.info(f"Executing IPython in JUPYTER_SERVER mode with kernel_id={kernel_id}")
            return await self._execute_via_kernel_manager(
                kernel_manager=kernel_manager,
                kernel_id=kernel_id,
                code=code,
                timeout=timeout,
                safe_extract_outputs_fn=safe_extract_outputs_fn
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
                server_client=server_client
            )
        
        else:
            return [f"[ERROR: Invalid mode or missing required managers]"]

