"""Execute IPython code directly in kernel tool."""

import asyncio
import logging
from typing import Union
from mcp.types import ImageContent

from ._base import BaseTool, ServerMode

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
    
    async def execute(
        self,
        mode: ServerMode,
        code: str,
        timeout: int = 60,
        ensure_kernel_alive_fn=None,
        wait_for_kernel_idle_fn=None,
        safe_extract_outputs_fn=None,
    ) -> list[Union[str, ImageContent]]:
        """Execute IPython code directly in the kernel.
        
        Args:
            mode: Server mode (ignored, uses notebook manager)
            code: IPython code to execute (supports magic commands, shell commands with !, and Python code)
            timeout: Execution timeout in seconds (default: 60s)
            ensure_kernel_alive_fn: Function to ensure kernel is alive
            wait_for_kernel_idle_fn: Function to wait for kernel idle state
            safe_extract_outputs_fn: Function to safely extract outputs
            
        Returns:
            List of outputs from the executed code
        """
        if ensure_kernel_alive_fn is None:
            raise ValueError("ensure_kernel_alive_fn is required")
        if wait_for_kernel_idle_fn is None:
            raise ValueError("wait_for_kernel_idle_fn is required")
        if safe_extract_outputs_fn is None:
            raise ValueError("safe_extract_outputs_fn is required")
        
        # Get current notebook name and kernel
        current_notebook = self.notebook_manager.get_current_notebook() or "default"
        kernel = self.notebook_manager.get_kernel(current_notebook)
        
        if not kernel:
            # Ensure kernel is alive
            kernel = ensure_kernel_alive_fn()
        
        # Wait for kernel to be idle before executing
        await wait_for_kernel_idle_fn(kernel, max_wait_seconds=30)
        
        logger.info(f"Executing IPython code with timeout {timeout}s: {code[:100]}...")
        
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
