# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Execute IPython code directly in kernel tool."""

import asyncio
import logging
from typing import Union

from mcp.types import ImageContent

from ._base import BaseTool, ServerMode
from ..notebook_manager import NotebookManager

logger = logging.getLogger(__name__)


class ExecuteIpythonTool(BaseTool):
    """Execute IPython code directly in the kernel on the current active notebook.
    
    This powerful tool supports:
    1. Magic commands (e.g., %timeit, %who, %load, %run, %matplotlib)
    2. Shell commands (e.g., !pip install, !ls, !cat)
    3. Python code (e.g., print(df.head()), df.info())
    
    Use cases:
    - Performance profiling and debugging
    - Environment exploration and package management
    - Variable inspection and data analysis
    - File system operations on Jupyter server
    - Temporary calculations and quick tests
    """
    
    @property
    def name(self) -> str:
        return "execute_ipython"
    
    @property
    def description(self) -> str:
        return "Execute IPython code directly in the kernel (supports magic commands, shell commands, and Python code)"
    
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
            notebook_path="",  # Not needed for execute_ipython
            code=code,
            kernel_id=kernel_id,
            timeout=timeout,
            logger=logger
        )
    
    async def _execute_via_notebook_manager(
        self,
        notebook_manager: NotebookManager,
        code: str,
        timeout: int,
        ensure_kernel_alive_fn,
        wait_for_kernel_idle_fn,
        safe_extract_outputs_fn
    ) -> list[Union[str, ImageContent]]:
        """Execute code using notebook_manager (MCP_SERVER mode - original logic)."""
        # Get current notebook name and kernel
        current_notebook = notebook_manager.get_current_notebook() or "default"
        kernel = notebook_manager.get_kernel(current_notebook)
        
        if not kernel:
            # Ensure kernel is alive
            kernel = ensure_kernel_alive_fn()
        
        # Wait for kernel to be idle before executing
        await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
        
        logger.info(f"Executing IPython code (MCP_SERVER) with timeout {timeout}s: {code[:100]}...")
        
        try:
            # Execute code directly with kernel
            execution_task = asyncio.create_task(
                asyncio.to_thread(kernel.execute, code)
            )
            
            # Wait for execution with timeout
            try:
                outputs = await asyncio.wait_for(execution_task, timeout=timeout)
            except asyncio.TimeoutError:
                execution_task.cancel()
                try:
                    if kernel and hasattr(kernel, 'interrupt'):
                        kernel.interrupt()
                        logger.info("Sent interrupt signal to kernel due to timeout")
                except Exception as interrupt_err:
                    logger.error(f"Failed to interrupt kernel: {interrupt_err}")
                
                return [f"[TIMEOUT ERROR: IPython execution exceeded {timeout} seconds and was interrupted]"]
            
            # Process and extract outputs
            if outputs:
                result = safe_extract_outputs_fn(outputs['outputs'])
                logger.info(f"IPython execution completed successfully with {len(result)} outputs")
                return result
            else:
                return ["[No output generated]"]
                
        except Exception as e:
            logger.error(f"Error executing IPython code: {e}")
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
            server_client: JupyterServerClient (not used)
            contents_manager: Contents manager (not used)
            kernel_manager: Kernel manager (for JUPYTER_SERVER mode)
            kernel_spec_manager: Kernel spec manager (not used)
            notebook_manager: Notebook manager (for MCP_SERVER mode)
            code: IPython code to execute (supports magic commands, shell commands with !, and Python code)
            timeout: Execution timeout in seconds (default: 60s)
            kernel_id: Kernel ID (for JUPYTER_SERVER mode)
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
                logger.info("No kernel_id available, starting new kernel for execute_ipython")
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
            
            logger.info("Executing IPython in MCP_SERVER mode")
            return await self._execute_via_notebook_manager(
                notebook_manager=notebook_manager,
                code=code,
                timeout=timeout,
                ensure_kernel_alive_fn=ensure_kernel_alive_fn,
                wait_for_kernel_idle_fn=wait_for_kernel_idle_fn,
                safe_extract_outputs_fn=safe_extract_outputs_fn
            )
        
        else:
            return [f"[ERROR: Invalid mode or missing required managers]"]

