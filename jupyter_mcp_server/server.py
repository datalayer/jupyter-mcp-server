# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

import logging
import click
import httpx
import uvicorn
from typing import Union, Optional
from fastapi import Request
from jupyter_kernel_client import KernelClient
from jupyter_server_api import JupyterServerClient
from mcp.server import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from jupyter_mcp_server.models import DocumentRuntime
from jupyter_mcp_server.utils import (
    extract_output, 
    safe_extract_outputs, 
    create_kernel,
    start_kernel,
    ensure_kernel_alive,
    execute_cell_with_timeout,
    execute_cell_with_forced_sync,
    is_kernel_busy,
    wait_for_kernel_idle,
    safe_notebook_operation,
    list_files_recursively,
)
from jupyter_mcp_server.config import get_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.enroll import auto_enroll_document
from jupyter_mcp_server.tools import (
    # Tool infrastructure
    ServerMode,
    # Notebook Management
    ListNotebooksTool,
    UseNotebookTool,
    RestartNotebookTool,
    UnuseNotebookTool,
    # Cell Reading
    ReadCellsTool,
    ListCellsTool,
    ReadCellTool,
    # Cell Writing
    InsertCellTool,
    InsertExecuteCodeCellTool,
    OverwriteCellSourceTool,
    DeleteCellTool,
    # Cell Execution
    ExecuteCellSimpleTimeoutTool,
    ExecuteCellStreamingTool,
    ExecuteCellWithProgressTool,
    # Other Tools
    AssignKernelToNotebookTool,
    ExecuteIpythonTool,
    ListFilesTool,
    ListKernelsTool,
)
from typing import Literal, Union
from mcp.types import ImageContent


###############################################################################


logger = logging.getLogger(__name__)


###############################################################################

class FastMCPWithCORS(FastMCP):
    def streamable_http_app(self) -> Starlette:
        """Return StreamableHTTP server app with CORS middleware
        See: https://github.com/modelcontextprotocol/python-sdk/issues/187
        """
        # Get the original Starlette app
        app = super().streamable_http_app()
        
        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # In production, should set specific domains
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        return app
    
    def sse_app(self, mount_path: str | None = None) -> Starlette:
        """Return SSE server app with CORS middleware"""
        # Get the original Starlette app
        app = super().sse_app(mount_path)
        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # In production, should set specific domains
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )        
        return app


###############################################################################


mcp = FastMCPWithCORS(name="Jupyter MCP Server", json_response=False, stateless_http=True)

# Initialize the unified notebook manager
notebook_manager = NotebookManager()

# Initialize all tool instances (no arguments needed - tools receive dependencies via execute())
# Notebook Management Tools
list_notebook_tool = ListNotebooksTool()
use_notebook_tool = UseNotebookTool()
restart_notebook_tool = RestartNotebookTool()
unuse_notebook_tool = UnuseNotebookTool()

# Cell Reading Tools
read_cells_tool = ReadCellsTool()
list_cells_tool = ListCellsTool()
read_cell_tool = ReadCellTool()

# Cell Writing Tools
insert_cell_tool = InsertCellTool()
insert_execute_code_cell_tool = InsertExecuteCodeCellTool()
overwrite_cell_source_tool = OverwriteCellSourceTool()
delete_cell_tool = DeleteCellTool()

# Cell Execution Tools
execute_cell_simple_timeout_tool = ExecuteCellSimpleTimeoutTool()
execute_cell_streaming_tool = ExecuteCellStreamingTool()
execute_cell_with_progress_tool = ExecuteCellWithProgressTool()

# Other Tools
assign_kernel_to_notebook_tool = AssignKernelToNotebookTool()
execute_ipython_tool = ExecuteIpythonTool()
list_files_tool = ListFilesTool()
list_kernel_tool = ListKernelsTool()


###############################################################################


class ServerContext:
    """Singleton to cache server mode and context managers."""
    _instance = None
    _mode = None
    _contents_manager = None
    _kernel_manager = None
    _kernel_spec_manager = None
    _session_manager = None
    _server_client = None
    _kernel_client = None
    _initialized = False
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset the singleton instance. Use this when config changes."""
        if cls._instance is not None:
            cls._instance._initialized = False
            cls._instance._mode = None
            cls._instance._contents_manager = None
            cls._instance._kernel_manager = None
            cls._instance._kernel_spec_manager = None
            cls._instance._session_manager = None
            cls._instance._server_client = None
            cls._instance._kernel_client = None
    
    def initialize(self):
        """Initialize context once."""
        if self._initialized:
            return
        
        try:
            from jupyter_mcp_server.jupyter_extension.context import get_server_context
            context = get_server_context()
            
            if context.is_local_document() and context.get_contents_manager() is not None:
                self._mode = ServerMode.JUPYTER_SERVER
                self._contents_manager = context.get_contents_manager()
                self._kernel_manager = context.get_kernel_manager()
                self._kernel_spec_manager = context.get_kernel_spec_manager() if hasattr(context, 'get_kernel_spec_manager') else None
                self._session_manager = context.get_session_manager() if hasattr(context, 'get_session_manager') else None
            else:
                self._mode = ServerMode.MCP_SERVER
                # Initialize HTTP clients for MCP_SERVER mode
                config = get_config()
                
                # Validate that runtime_url is set and not None/empty
                # Note: String "None" values should have been normalized by start_command()
                runtime_url = config.runtime_url
                if not runtime_url or runtime_url in ("None", "none", "null", ""):
                    raise ValueError(
                        f"runtime_url is not configured (current value: {repr(runtime_url)}). "
                        "Please check:\n"
                        "1. RUNTIME_URL environment variable is set correctly (not the string 'None')\n"
                        "2. --runtime-url argument is provided when starting the server\n"
                        "3. The MCP client configuration passes runtime_url correctly"
                    )
                
                logger.info(f"Initializing MCP_SERVER mode with runtime_url: {runtime_url}")
                self._server_client = JupyterServerClient(base_url=runtime_url, token=config.runtime_token)
                # kernel_client will be created lazily when needed
        except (ImportError, Exception) as e:
            # If not in Jupyter context, use MCP_SERVER mode
            if not isinstance(e, ValueError):
                self._mode = ServerMode.MCP_SERVER
                # Initialize HTTP clients for MCP_SERVER mode
                config = get_config()
                
                # Validate that runtime_url is set and not None/empty
                # Note: String "None" values should have been normalized by start_command()
                runtime_url = config.runtime_url
                if not runtime_url or runtime_url in ("None", "none", "null", ""):
                    raise ValueError(
                        f"runtime_url is not configured (current value: {repr(runtime_url)}). "
                        "Please check:\n"
                        "1. RUNTIME_URL environment variable is set correctly (not the string 'None')\n"
                        "2. --runtime-url argument is provided when starting the server\n"
                        "3. The MCP client configuration passes runtime_url correctly"
                    )
                
                logger.info(f"Initializing MCP_SERVER mode with runtime_url: {runtime_url}")
                self._server_client = JupyterServerClient(base_url=runtime_url, token=config.runtime_token)
            else:
                raise
        
        self._initialized = True
        logger.info(f"Server mode initialized: {self._mode}")
    
    @property
    def mode(self):
        if not self._initialized:
            self.initialize()
        return self._mode
    
    @property
    def contents_manager(self):
        if not self._initialized:
            self.initialize()
        return self._contents_manager
    
    @property
    def kernel_manager(self):
        if not self._initialized:
            self.initialize()
        return self._kernel_manager
    
    @property
    def kernel_spec_manager(self):
        if not self._initialized:
            self.initialize()
        return self._kernel_spec_manager
    
    @property
    def session_manager(self):
        if not self._initialized:
            self.initialize()
        return self._session_manager
    
    @property
    def server_client(self):
        if not self._initialized:
            self.initialize()
        return self._server_client
    
    @property
    def kernel_client(self):
        if not self._initialized:
            self.initialize()
        return self._kernel_client


# Initialize server context singleton
server_context = ServerContext.get_instance()


###############################################################################


def __create_kernel() -> KernelClient:
    """Create a new kernel instance using current configuration."""
    config = get_config()
    return create_kernel(config, logger)


def __start_kernel():
    """Start the Jupyter kernel with error handling (for backward compatibility)."""
    config = get_config()
    start_kernel(notebook_manager, config, logger)


async def __auto_enroll_document():
    """Wrapper for auto_enroll_document that uses server context."""
    await auto_enroll_document(
        config=get_config(),
        notebook_manager=notebook_manager,
        use_notebook_tool=use_notebook_tool,
        server_context=server_context,
    )


def __ensure_kernel_alive() -> KernelClient:
    """Ensure kernel is running, restart if needed."""
    current_notebook = notebook_manager.get_current_notebook() or "default"
    return ensure_kernel_alive(notebook_manager, current_notebook, __create_kernel)


async def __execute_cell_with_timeout(notebook, cell_index, kernel, timeout_seconds=300):
    """Execute a cell with timeout and real-time output sync."""
    return await execute_cell_with_timeout(notebook, cell_index, kernel, timeout_seconds, logger)


async def __execute_cell_with_forced_sync(notebook, cell_index, kernel, timeout_seconds=300):
    """Execute cell with forced real-time synchronization."""
    return await execute_cell_with_forced_sync(notebook, cell_index, kernel, timeout_seconds, logger)


def __is_kernel_busy(kernel):
    """Check if kernel is currently executing something."""
    return is_kernel_busy(kernel)


async def __wait_for_kernel_idle(kernel, max_wait_seconds=60):
    """Wait for kernel to become idle before proceeding."""
    return await wait_for_kernel_idle(kernel, logger, max_wait_seconds)


async def __safe_notebook_operation(operation_func, max_retries=3):
    """Safely execute notebook operations with connection recovery."""
    return await safe_notebook_operation(operation_func, logger, max_retries)


def _list_files_recursively(server_client, current_path="", current_depth=0, files=None, max_depth=3):
    """Recursively list all files and directories in the Jupyter server."""
    return list_files_recursively(server_client, current_path, current_depth, files, max_depth)


###############################################################################
# Custom Routes.


@mcp.custom_route("/api/connect", ["PUT"])
async def connect(request: Request):
    """Connect to a document and a runtime from the Jupyter MCP server."""

    data = await request.json()
    
    # Log the received data for diagnostics
    # Note: set_config() will automatically normalize string "None" values
    logger.info(
        f"Connect endpoint received - runtime_url: {repr(data.get('runtime_url'))}, "
        f"document_url: {repr(data.get('document_url'))}, "
        f"provider: {data.get('provider')}"
    )

    document_runtime = DocumentRuntime(**data)

    # Clean up existing default notebook if any
    if "default" in notebook_manager:
        try:
            notebook_manager.remove_notebook("default")
        except Exception as e:
            logger.warning(f"Error stopping existing notebook during connect: {e}")

    # Update configuration with new values
    # String "None" values will be automatically normalized by set_config()
    set_config(
        provider=document_runtime.provider,
        runtime_url=document_runtime.runtime_url,
        runtime_id=document_runtime.runtime_id,
        runtime_token=document_runtime.runtime_token,
        document_url=document_runtime.document_url,
        document_id=document_runtime.document_id,
        document_token=document_runtime.document_token
    )
    
    # Reset ServerContext to pick up new configuration
    ServerContext.reset()

    try:
        __start_kernel()
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@mcp.custom_route("/api/stop", ["DELETE"])
async def stop(request: Request):
    try:
        current_notebook = notebook_manager.get_current_notebook() or "default"
        if current_notebook in notebook_manager:
            notebook_manager.remove_notebook(current_notebook)
        return JSONResponse({"success": True})
    except Exception as e:
        logger.error(f"Error stopping notebook: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@mcp.custom_route("/api/healthz", ["GET"])
async def health_check(request: Request):
    """Custom health check endpoint"""
    kernel_status = "unknown"
    try:
        current_notebook = notebook_manager.get_current_notebook() or "default"
        kernel = notebook_manager.get_kernel(current_notebook)
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
###############################################################################

###############################################################################
# Multi-Notebook Management Tools.


@mcp.tool()
async def use_notebook(
    notebook_name: str,
    notebook_path: Optional[str] = None,
    mode: Literal["connect", "create"] = "connect",
    kernel_id: Optional[str] = None,
) -> str:
    """Use a notebook file (connect to existing or create new, or switch to already-connected notebook).
    
    Args:
        notebook_name: Unique identifier for the notebook
        notebook_path: Path to the notebook file, relative to the Jupyter server root (e.g. "notebook.ipynb"). 
                      Optional - if not provided, switches to an already-connected notebook with the given name.
        mode: "connect" to connect to existing, "create" to create new
        kernel_id: Specific kernel ID to use (optional, will create new if not provided)
        
    Returns:
        str: Success message with notebook information
    """
    config = get_config()
    return await __safe_notebook_operation(
        lambda: use_notebook_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            notebook_name=notebook_name,
            notebook_path=notebook_path,
            use_mode=mode,
            kernel_id=kernel_id,
            ensure_kernel_alive_fn=__ensure_kernel_alive,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            session_manager=server_context.session_manager,
            notebook_manager=notebook_manager,
            runtime_url=config.runtime_url if config.runtime_url != "local" else None,
            runtime_token=config.runtime_token,
        )
    )


@mcp.tool()
async def list_notebooks() -> str:
    """List all notebooks in the Jupyter server (including subdirectories) and show which ones are managed.
    
    To interact with a notebook, it has to be "managed". If a notebook is not managed, you can use it with the `use_notebook` tool.
    
    Returns:
        str: TSV formatted table with notebook information including management status
    """
    return await list_notebook_tool.execute(
        mode=server_context.mode,
        server_client=server_context.server_client,
        contents_manager=server_context.contents_manager,
        kernel_manager=server_context.kernel_manager,
        notebook_manager=notebook_manager,
    )


@mcp.tool()
async def restart_notebook(notebook_name: str) -> str:
    """Restart the kernel for a specific notebook.
    
    Args:
        notebook_name: Notebook identifier to restart
        
    Returns:
        str: Success message
    """
    return await restart_notebook_tool.execute(
        mode=server_context.mode,
        notebook_name=notebook_name,
        notebook_manager=notebook_manager,
        kernel_manager=server_context.kernel_manager,
    )


@mcp.tool()
async def unuse_notebook(notebook_name: str) -> str:
    """Unuse from a specific notebook and release its resources.
    
    Args:
        notebook_name: Notebook identifier to disconnect
        
    Returns:
        str: Success message
    """
    return await unuse_notebook_tool.execute(
        mode=server_context.mode,
        notebook_name=notebook_name,
        notebook_manager=notebook_manager,
        kernel_manager=server_context.kernel_manager,
    )


###############################################################################
# Cell Tools.

@mcp.tool()
async def insert_cell(
    cell_index: int,
    cell_type: Literal["code", "markdown"],
    cell_source: str,
) -> str:
    """Insert a cell to specified position.

    Args:
        cell_index: target index for insertion (0-based). Use -1 to append at end.
        cell_type: Type of cell to insert ("code" or "markdown")
        cell_source: Source content for the cell

    Returns:
        str: Success message and the structure of its surrounding cells (up to 5 cells above and 5 cells below)
    """
    return await __safe_notebook_operation(
        lambda: insert_cell_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            cell_source=cell_source,
            cell_type=cell_type,
        )
    )


@mcp.tool()
async def insert_execute_code_cell(cell_index: int, cell_source: str) -> list[Union[str, ImageContent]]:
    """Insert and execute a code cell in a Jupyter notebook.

    Args:
        cell_index: Index of the cell to insert (0-based). Use -1 to append at end and execute.
        cell_source: Code source

    Returns:
        list[Union[str, ImageContent]]: List of outputs from the executed cell
    """
    return await __safe_notebook_operation(
        lambda: insert_execute_code_cell_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            cell_source=cell_source,
            ensure_kernel_alive=__ensure_kernel_alive,
        )
    )


@mcp.tool()
async def overwrite_cell_source(cell_index: int, cell_source: str) -> str:
    """Overwrite the source of an existing cell.
       Note this does not execute the modified cell by itself.

    Args:
        cell_index: Index of the cell to overwrite (0-based)
        cell_source: New cell source - must match existing cell type

    Returns:
        str: Success message with diff showing changes made
    """
    return await __safe_notebook_operation(
        lambda: overwrite_cell_source_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            cell_source=cell_source,
        )
    )

@mcp.tool()
async def execute_cell_with_progress(cell_index: int, timeout_seconds: int = 300) -> list[Union[str, ImageContent]]:
    """Execute a specific cell with timeout and progress monitoring.
    Args:
        cell_index: Index of the cell to execute (0-based)
        timeout_seconds: Maximum time to wait for execution (default: 300s)
    Returns:
        list[Union[str, ImageContent]]: List of outputs from the executed cell
    """
    return await __safe_notebook_operation(
        lambda: execute_cell_with_progress_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            timeout_seconds=timeout_seconds,
            ensure_kernel_alive_fn=__ensure_kernel_alive,
            wait_for_kernel_idle_fn=__wait_for_kernel_idle,
            safe_extract_outputs_fn=safe_extract_outputs,
            execute_cell_with_forced_sync_fn=__execute_cell_with_forced_sync,
        ),
        max_retries=1
    )

# Simpler real-time monitoring without forced sync
@mcp.tool()
async def execute_cell_simple_timeout(cell_index: int, timeout_seconds: int = 300) -> list[Union[str, ImageContent]]:
    """Execute a cell with simple timeout (no forced real-time sync). To be used for short-running cells.
    This won't force real-time updates but will work reliably.
    """
    return await __safe_notebook_operation(
        lambda: execute_cell_simple_timeout_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            timeout_seconds=timeout_seconds,
            ensure_kernel_alive_fn=__ensure_kernel_alive,
            wait_for_kernel_idle_fn=__wait_for_kernel_idle,
            safe_extract_outputs_fn=safe_extract_outputs,
        ),
        max_retries=1
    )


@mcp.tool()
async def execute_cell_streaming(cell_index: int, timeout_seconds: int = 300, progress_interval: int = 5) -> list[Union[str, ImageContent]]:
    """Execute cell with streaming progress updates. To be used for long-running cells.
    Args:
        cell_index: Index of the cell to execute (0-based)
        timeout_seconds: Maximum time to wait for execution (default: 300s)  
        progress_interval: Seconds between progress updates (default: 5s)
    Returns:
        list[Union[str, ImageContent]]: List of outputs including progress updates
    """
    return await __safe_notebook_operation(
        lambda: execute_cell_streaming_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            timeout_seconds=timeout_seconds,
            progress_interval=progress_interval,
            ensure_kernel_alive_fn=__ensure_kernel_alive,
            wait_for_kernel_idle_fn=__wait_for_kernel_idle,
            extract_output_fn=extract_output,
        ),
        max_retries=1
    )

@mcp.tool()
async def read_cells() -> list[dict[str, Union[str, int, list[Union[str, ImageContent]]]]]:
    """Read all cells from the Jupyter notebook.
    Returns:
        list[dict]: List of cell information including index, type, source,
                    and outputs (for code cells)
    """
    return await __safe_notebook_operation(
        lambda: read_cells_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
        )
    )


@mcp.tool()
async def list_cells() -> str:
    """List the basic information of all cells in the notebook.
    
    Returns a formatted table showing the index, type, execution count (for code cells),
    and first line of each cell. This provides a quick overview of the notebook structure
    and is useful for locating specific cells for operations like delete or insert.
    
    Returns:
        str: Formatted table with cell information (Index, Type, Count, First Line)
    """
    return await __safe_notebook_operation(
        lambda: list_cells_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
        )
    )


@mcp.tool()
async def read_cell(cell_index: int) -> dict[str, Union[str, int, list[Union[str, ImageContent]]]]:
    """Read a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to read (0-based)
    Returns:
        dict: Cell information including index, type, source, and outputs (for code cells)
    """
    return await __safe_notebook_operation(
        lambda: read_cell_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
        )
    )

@mcp.tool()
async def delete_cell(cell_index: int) -> str:
    """Delete a specific cell from the Jupyter notebook.
    Args:
        cell_index: Index of the cell to delete (0-based)
    Returns:
        str: Success message
    """
    return await __safe_notebook_operation(
        lambda: delete_cell_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
        )
    )


@mcp.tool()
async def execute_ipython(code: str, timeout: int = 60) -> list[Union[str, ImageContent]]:
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

    Args:
        code: IPython code to execute (supports magic commands, shell commands with !, and Python code)
        timeout: Execution timeout in seconds (default: 60s)
    Returns:
        List of outputs from the executed code
    """
    # Get kernel_id for JUPYTER_SERVER mode
    # Let the tool handle getting kernel_id via get_current_notebook_context()
    kernel_id = None
    if server_context.mode == ServerMode.JUPYTER_SERVER:
        current_notebook = notebook_manager.get_current_notebook() or "default"
        kernel_id = notebook_manager.get_kernel_id(current_notebook)
        # Note: kernel_id might be None here if notebook not in manager,
        # but the tool will fall back to config values via get_current_notebook_context()
    
    return await __safe_notebook_operation(
        lambda: execute_ipython_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            code=code,
            timeout=timeout,
            kernel_id=kernel_id,
            ensure_kernel_alive_fn=__ensure_kernel_alive,
            wait_for_kernel_idle_fn=__wait_for_kernel_idle,
            safe_extract_outputs_fn=safe_extract_outputs,
        ),
        max_retries=1
    )


@mcp.tool()
async def list_files(path: str = "", max_depth: int = 3) -> str:
    """List all files and directories in the Jupyter server's file system.
    
    This tool recursively lists files and directories from the Jupyter server's content API,
    showing the complete file structure including notebooks, data files, scripts, and directories.
    
    Args:
        path: The starting path to list from (empty string means root directory)
        max_depth: Maximum depth to recurse into subdirectories (default: 3)
        
    Returns:
        str: Tab-separated table with columns: Path, Type, Size, Last_Modified
    """
    return await __safe_notebook_operation(
        lambda: list_files_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            path=path,
            max_depth=max_depth,
            list_files_recursively_fn=_list_files_recursively,
        )
    )


@mcp.tool()
async def list_kernels() -> str:
    """List all available kernels in the Jupyter server.
    
    This tool shows all running and available kernel sessions on the Jupyter server,
    including their IDs, names, states, connection information, and kernel specifications.
    Useful for monitoring kernel resources and identifying specific kernels for connection.
    
    Returns:
        str: Tab-separated table with columns: ID, Name, Display_Name, Language, State, Connections, Last_Activity, Environment
    """
    return await __safe_notebook_operation(
        lambda: list_kernel_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            kernel_manager=server_context.kernel_manager,
            kernel_spec_manager=server_context.kernel_spec_manager,
        )
    )


@mcp.tool()
async def assign_kernel_to_notebook(
    notebook_path: str,
    kernel_id: str,
    session_name: str = None
) -> str:
    """Assign a kernel to a notebook by creating a Jupyter session.
    
    This creates a Jupyter server session that connects a notebook file to a kernel,
    enabling code execution in the notebook. Sessions are the mechanism Jupyter uses
    to maintain the relationship between notebooks and their kernels.
    
    Args:
        notebook_path: Path to the notebook file, relative to the Jupyter server root (e.g. "notebook.ipynb")
        kernel_id: ID of the kernel to assign to the notebook
        session_name: Optional name for the session (defaults to notebook path)
    
    Returns:
        str: Success message with session information including session ID
    """
    return await __safe_notebook_operation(
        lambda: assign_kernel_to_notebook_tool.execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            session_manager=server_context.session_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_path=notebook_path,
            kernel_id=kernel_id,
            session_name=session_name,
        )
    )


###############################################################################
# Helper Functions for Extension.


async def get_registered_tools():
    """
    Get list of all registered MCP tools with their metadata.
    
    This function is used by the Jupyter extension to dynamically expose
    the tool registry without hardcoding tool names and parameters.
    
    Returns:
        list: List of tool dictionaries with name, description, and inputSchema
    """
    # Use FastMCP's list_tools method which returns Tool objects
    tools_list = await mcp.list_tools()
    
    tools = []
    for tool in tools_list:
        tool_dict = {
            "name": tool.name,
            "description": tool.description,
        }
        
        # Extract parameter names from inputSchema
        if hasattr(tool, 'inputSchema') and tool.inputSchema:
            input_schema = tool.inputSchema
            if 'properties' in input_schema:
                tool_dict["parameters"] = list(input_schema['properties'].keys())
            else:
                tool_dict["parameters"] = []
            
            # Include full inputSchema for MCP protocol compatibility
            tool_dict["inputSchema"] = input_schema
        else:
            tool_dict["parameters"] = []
        
        tools.append(tool_dict)
    
    return tools


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
    help="The provider to use for the document and runtime. Defaults to 'jupyter'.",
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
    help="The runtime token to use for authentication with the provider.  For the jupyter provider, this is the jupyter token. For the datalayer provider, this is the datalayer token. If not provided, the provider should accept anonymous requests.",
)
@click.option(
    "--document-url",
    envvar="DOCUMENT_URL",
    type=click.STRING,
    default="http://localhost:8888",
    help="The document URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer document URL.",
)
@click.option(
    "--document-id",
    envvar="DOCUMENT_ID",
    type=click.STRING,
    default="notebook.ipynb",
    help="The document id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path.",
)
@click.option(
    "--document-token",
    envvar="DOCUMENT_TOKEN",
    type=click.STRING,
    default=None,
    help="The document token to use for authentication with the provider. For the jupyter provider, this is the jupyter token. For the datalayer provider, this is the datalayer token. If not provided, the provider should accept anonymous requests.",
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
    document_url: str,
    document_id: str,
    document_token: str,
    provider: str,
):
    """Command to connect a Jupyter MCP Server to a document and a runtime."""

    # Set configuration using the singleton
    set_config(
        provider=provider,
        runtime_url=runtime_url,
        runtime_id=runtime_id,
        runtime_token=runtime_token,
        document_url=document_url,
        document_id=document_id,
        document_token=document_token
    )

    config = get_config()
    
    document_runtime = DocumentRuntime(
        provider=config.provider,
        runtime_url=config.runtime_url,
        runtime_id=config.runtime_id,
        runtime_token=config.runtime_token,
        document_url=config.document_url,
        document_id=config.document_id,
        document_token=config.document_token,
    )

    r = httpx.put(
        f"{jupyter_mcp_server_url}/api/connect",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        content=document_runtime.model_dump_json(),
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
    help="The provider to use for the document and runtime. Defaults to 'jupyter'.",
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
    "--document-url",
    envvar="DOCUMENT_URL",
    type=click.STRING,
    default="http://localhost:8888",
    help="The document URL to use. For the jupyter provider, this is the Jupyter server URL. For the datalayer provider, this is the Datalayer document URL.",
)
@click.option(
    "--document-id",
    envvar="DOCUMENT_ID",
    type=click.STRING,
    default="notebook.ipynb",
    help="The document id to use. For the jupyter provider, this is the notebook path. For the datalayer provider, this is the notebook path.",
)
@click.option(
    "--document-token",
    envvar="DOCUMENT_TOKEN",
    type=click.STRING,
    default=None,
    help="The document token to use for authentication with the provider. If not provided, the provider should accept anonymous requests.",
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
    document_url: str,
    document_id: str,
    document_token: str,
    port: int,
    provider: str,
):
    """Start the Jupyter MCP server with a transport."""

    # Log the received configuration for diagnostics
    # Note: set_config() will automatically normalize string "None" values
    logger.info(
        f"Start command received - runtime_url: {repr(runtime_url)}, "
        f"document_url: {repr(document_url)}, provider: {provider}, "
        f"transport: {transport}"
    )

    # Set configuration using the singleton
    # String "None" values will be automatically normalized by set_config()
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
        port=port
    )
    
    # Reset ServerContext to pick up new configuration
    ServerContext.reset()

    # Determine startup behavior based on configuration
    if config.document_id:
        # If document_id is provided, auto-enroll the notebook
        # Kernel creation depends on start_new_runtime and runtime_id flags
        try:
            import asyncio
            # Run the async enrollment in the event loop
            asyncio.run(__auto_enroll_document())
        except Exception as e:
            logger.error(f"Failed to auto-enroll document '{config.document_id}': {e}")
            # Fallback to legacy kernel-only mode if enrollment fails
            if config.start_new_runtime or config.runtime_id:
                try:
                    __start_kernel()
                except Exception as e2:
                    logger.error(f"Failed to start kernel on startup: {e2}")
    elif config.start_new_runtime or config.runtime_id:
        # If no document_id but start_new_runtime/runtime_id is set, just create kernel
        # This is for backward compatibility - kernel without managed notebook
        try:
            __start_kernel()
        except Exception as e:
            logger.error(f"Failed to start kernel on startup: {e}")
    # else: No startup action - user must manually enroll notebooks or create kernels

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