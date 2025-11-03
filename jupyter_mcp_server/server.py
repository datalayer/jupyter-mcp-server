# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Jupyter MCP Server Layer
"""

from typing import Annotated, Literal
from pydantic import Field
from fastapi import Request
from jupyter_kernel_client import KernelClient

from mcp.server import FastMCP
from mcp.types import ImageContent
from starlette.middleware.cors import CORSMiddleware
from starlette.applications import Starlette
from starlette.responses import JSONResponse

from jupyter_mcp_server.log import logger
from jupyter_mcp_server.models import DocumentRuntime
from jupyter_mcp_server.utils import (
    safe_extract_outputs, 
    create_kernel,
    start_kernel,
    ensure_kernel_alive,
    wait_for_kernel_idle,
    safe_notebook_operation
)
from jupyter_mcp_server.config import get_config, set_config
from jupyter_mcp_server.notebook_manager import NotebookManager
from jupyter_mcp_server.server_context import ServerContext
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
    ReadNotebookTool,
    ReadCellTool,
    # Cell Writing
    InsertCellTool,
    OverwriteCellSourceTool,
    DeleteCellTool,
    # Cell Execution
    ExecuteCellTool,
    # Other Tools
    ExecuteCodeTool,
    ListFilesTool,
    ListKernelsTool,
    # MCP Prompt
    JupyterCitePrompt,
)


###############################################################################
# Globals.

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

mcp = FastMCPWithCORS(name="Jupyter MCP Server", json_response=False, stateless_http=True)
notebook_manager = NotebookManager()
server_context = ServerContext.get_instance()

def __start_kernel():
    """Start the Jupyter kernel with error handling (for backward compatibility)."""
    config = get_config()
    start_kernel(notebook_manager, config, logger)

async def __auto_enroll_document():
    """Wrapper for auto_enroll_document that uses server context."""
    await auto_enroll_document(
        config=get_config(),
        notebook_manager=notebook_manager,
        use_notebook_tool=UseNotebookTool(),
        server_context=server_context,
    )


def __ensure_kernel_alive() -> KernelClient:
    """Ensure kernel is running, restart if needed."""
    def __create_kernel() -> KernelClient:
        """Create a new kernel instance using current configuration."""
        config = get_config()
        return create_kernel(config, logger)
    current_notebook = notebook_manager.get_current_notebook() or "default"
    return ensure_kernel_alive(notebook_manager, current_notebook, __create_kernel)


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
# Server Management Tools.

@mcp.tool()
async def list_files(
    path: Annotated[str, Field(description="The starting path to list from (empty string means root directory)")] = "",
    # Maximum depth to recurse into subdirectories, Set Max to 3 to avoid infinite recursion.
    max_depth: Annotated[int, Field(description="Maximum depth to recurse into subdirectories", ge=0, le=3)] = 1,
    start_index: Annotated[int, Field(description="Starting index for pagination (0-based)", ge=0)] = 0,
    limit: Annotated[int, Field(description="Maximum number of items to return (0 means no limit)", ge=0)] = 25,
    pattern: Annotated[str, Field(description="Glob pattern to filter file paths")] = "",
) -> Annotated[str, Field(description="Tab-separated table with columns: Path, Type, Size, Last_Modified. Includes pagination info header.")]:
    """
    List all files and directories recursively in the Jupyter server's file system.
    Used to explore the file system structure of the Jupyter server or to find specific files or directories.
    """
    return await safe_notebook_operation(
        lambda: ListFilesTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            path=path,
            max_depth=max_depth,
            start_index=start_index,
            limit=limit,
            pattern=pattern if pattern else None,
        )
    )


@mcp.tool()
async def list_kernels() -> Annotated[str, Field(description="Tab-separated table with columns: ID, Name, Display_Name, Language, State, Connections, Last_Activity, Environment")]:
    """List all available kernels in the Jupyter server.
    
    This tool shows all running and available kernel sessions on the Jupyter server,
    including their IDs, names, states, connection information, and kernel specifications.
    Useful for monitoring kernel resources and identifying specific kernels for connection.
    """
    return await safe_notebook_operation(
        lambda: ListKernelsTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            kernel_manager=server_context.kernel_manager,
            kernel_spec_manager=server_context.kernel_spec_manager,
        )
    )

###############################################################################
# Multi-Notebook Management Tools.


@mcp.tool()
async def use_notebook(
    notebook_name: Annotated[str, Field(description="Unique identifier for the notebook")],
    notebook_path: Annotated[str, Field(description="Path to the notebook file, relative to the Jupyter server root (e.g. 'notebook.ipynb')")],
    mode: Annotated[Literal["connect", "create"], Field(description="Notebook operation mode: 'connect' to connect to existing and activate it, 'create' to create new and activate it")] = "connect",
    kernel_id: Annotated[str, Field(description="Specific kernel ID to use (will create new if skipped)")] = None,
) -> Annotated[str, Field(description="Success message with notebook information")]:
    """Use a notebook and activate it for following cell operations.
    All cell operations will be performed on the currently activated notebook.
    Activate new notebook will deactivate the previously activated notebook.
    Reactivate previously activated notebook using same notebook_name and notebook_path.
    """
    config = get_config()
    return await safe_notebook_operation(
        lambda: UseNotebookTool().execute(
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
async def list_notebooks() -> Annotated[str, Field(description="TSV formatted table with notebook information")]:
    """List all notebooks that have been used via use_notebook tool"""
    return await ListNotebooksTool().execute(
        mode=server_context.mode,
        notebook_manager=notebook_manager,
    )


@mcp.tool()
async def restart_notebook(
    notebook_name: Annotated[str, Field(description="Notebook identifier to restart")],
) -> Annotated[str, Field(description="Success message")]:
    """Restart the kernel for a specific notebook."""
    return await RestartNotebookTool().execute(
        mode=server_context.mode,
        notebook_name=notebook_name,
        notebook_manager=notebook_manager,
        kernel_manager=server_context.kernel_manager,
    )


@mcp.tool()
async def unuse_notebook(
    notebook_name: Annotated[str, Field(description="Notebook identifier to disconnect")],
) -> Annotated[str, Field(description="Success message")]:
    """Unuse from a specific notebook and release its resources."""
    return await UnuseNotebookTool().execute(
        mode=server_context.mode,
        notebook_name=notebook_name,
        notebook_manager=notebook_manager,
        kernel_manager=server_context.kernel_manager,
    )

@mcp.tool()
async def read_notebook(
    notebook_name: Annotated[str, Field(description="Notebook identifier to read")],
    response_format: Annotated[Literal["brief", "detailed"], Field(description="Response format: 'brief' will return first line and lines number, 'detailed' will return full cell source")] = "brief",
    start_index: Annotated[int, Field(description="Starting index for pagination (0-based)", ge=0)] = 0,
    limit: Annotated[int, Field(description="Maximum number of items to return (0 means no limit)", ge=0)] = 20
) -> Annotated[str, Field(description="Notebook content in the requested format")]:
    """Read a notebook and return index, source content, type, execution count of each cell.
    
    Using brief format to get a quick overview of the notebook structure and it's useful for locating specific cells for operations like delete or insert.
    Using detailed format to get detailed information of the notebook and it's useful for debugging and analysis.

    It is recommended to use brief format with larger limit to get a overview of the notebook structure, 
    then use detailed format with exact index and limit to get the detailed information of some specific cells.
    """
    return await safe_notebook_operation(
        lambda: ReadNotebookTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            notebook_name=notebook_name,
            response_format=response_format,
            start_index=start_index,
            limit=limit,
        )
    )

###############################################################################
# Cell Tools.

@mcp.tool()
async def insert_cell(
    cell_index: Annotated[int, Field(description="Target index for insertion (0-based), use -1 to append at end", ge=-1)],
    cell_type: Annotated[Literal["code", "markdown"], Field(description="Type of cell to insert")],
    cell_source: Annotated[str, Field(description="Source content for the cell")],
) -> Annotated[str, Field(description="Success message and the structure of its surrounding cells")]:
    """Insert a cell to specified position from the currently activated notebook."""
    return await safe_notebook_operation(
        lambda: InsertCellTool().execute(
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
async def overwrite_cell_source(
    cell_index: Annotated[int, Field(description="Index of the cell to overwrite (0-based)", ge=0)],
    cell_source: Annotated[str, Field(description="New complete cell source")],
) -> Annotated[str, Field(description="Success message with diff showing changes made")]:
    """Overwrite the source of a specific cell from the currently activated notebook.
    It will return a diff style comparison (e.g. `+` for new lines, `-` for deleted lines) of the cell's content"""
    return await safe_notebook_operation(
        lambda: OverwriteCellSourceTool().execute(
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
async def execute_cell(
    cell_index: Annotated[int, Field(description="Index of the cell to execute (0-based)", ge=0)],
    timeout: Annotated[int, Field(description="Maximum seconds to wait for execution")] = 90,
    stream: Annotated[bool, Field(description="Enable streaming progress (including time indicator) updates for long-running cells")] = False,
    progress_interval: Annotated[int, Field(description="Seconds between progress updates when stream=True")] = 5,
) -> Annotated[list[str | ImageContent], Field(description="List of outputs from the executed cell")]:
    """Execute a cell from the currently activated notebook with timeout and return it's outputs"""
    return await safe_notebook_operation(
        lambda: ExecuteCellTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            timeout_seconds=timeout,
            stream=stream,
            progress_interval=progress_interval,
            ensure_kernel_alive_fn=__ensure_kernel_alive
        ),
        max_retries=1
    )

@mcp.tool()
async def insert_execute_code_cell(
    cell_index: Annotated[int, Field(description="Index of the cell to insert and execute (0-based)", ge=0)],
    cell_source: Annotated[str, Field(description="Code source for the cell")],
    timeout: Annotated[int, Field(description="Maximum seconds to wait for execution")] = 90,
) -> Annotated[list[str | ImageContent], Field(description="List of outputs from the executed cell")]:
    """Insert a cell at specified index from the currently activated notebook and then execute it with timeout and return it's outputs
    It is a shortcut tool for insert_cell and execute_cell tools, recommended to use if you want to insert a cell and execute it at the same time"""
    await safe_notebook_operation(
        lambda: InsertCellTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            cell_source=cell_source,
            cell_type="code",
        )
    )

    return await safe_notebook_operation(
        lambda: ExecuteCellTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            timeout_seconds=timeout,
            stream=False,
            progress_interval=0,
            ensure_kernel_alive_fn=__ensure_kernel_alive
        ),
        max_retries=1
    )

@mcp.tool()
async def read_cell(
    cell_index: Annotated[int, Field(description="Index of the cell to read (0-based)", ge=0)],
    include_outputs: Annotated[bool, Field(description="Include outputs in the response (only for code cells)")] = True,
) -> Annotated[list[str | ImageContent], Field(description="Cell information including index, type, source, and outputs (for code cells)")]:
    """Read a specific cell from the currently activated notebook and return it's metadata (index, type, execution count), source and outputs (for code cells)"""
    return await safe_notebook_operation(
        lambda: ReadCellTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            cell_index=cell_index,
            include_outputs=include_outputs,
        )
    )

@mcp.tool()
async def delete_cell(
    cell_indices: Annotated[list[int], Field(description="List of cell indices to delete (0-based)",min_items=1)],
    include_source: Annotated[bool, Field(description="Whether to include the source of deleted cells")] = True,
) -> Annotated[str, Field(description="Success message with list of deleted cells and their source (if include_source=True)")]:
    """Delete specific cells from the currently activated notebook and return the cell source of deleted cells (if include_source=True)."""
    return await safe_notebook_operation(
        lambda: DeleteCellTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            cell_indices=cell_indices,
            include_source=include_source,
        )
    )


@mcp.tool()
async def execute_code(
    code: Annotated[str, Field(description="Code to execute (supports magic commands with %, shell commands with !)")],
    timeout: Annotated[int, Field(description="Execution timeout in seconds",le=60)] = 30,
) -> Annotated[list[str | ImageContent], Field(description="List of outputs from the executed code")]:
    """Execute code directly in the kernel (not saved to notebook) on the current activated notebook.

    Recommended to use in following cases:
    1. Execute Jupyter magic commands(e.g., `%timeit`, `%pip install xxx`)
    2. Performance profiling and debugging.
    3. View intermediate variable values(e.g., `print(xxx)`, `df.head()`)
    4. Temporary calculations and quick tests(e.g., `np.mean(df['xxx'])`)
    5. Execute Shell commands in Jupyter server(e.g., `!git xxx`)

    Under no circumstances should you use this tool to:
    1. Import new modules or perform variable assignments that affect subsequent Notebook execution
    2. Execute dangerous code that may harm the Jupyter server or the user's data without permission
    """
    # Get kernel_id for JUPYTER_SERVER mode
    # Let the tool handle getting kernel_id via get_current_notebook_context()
    kernel_id = None
    if server_context.mode == ServerMode.JUPYTER_SERVER:
        current_notebook = notebook_manager.get_current_notebook() or "default"
        kernel_id = notebook_manager.get_kernel_id(current_notebook)
        # Note: kernel_id might be None here if notebook not in manager,
        # but the tool will fall back to config values via get_current_notebook_context()
    
    return await safe_notebook_operation(
        lambda: ExecuteCodeTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            kernel_manager=server_context.kernel_manager,
            notebook_manager=notebook_manager,
            code=code,
            timeout=timeout,
            kernel_id=kernel_id,
            ensure_kernel_alive_fn=__ensure_kernel_alive,
            wait_for_kernel_idle_fn=wait_for_kernel_idle,
            safe_extract_outputs_fn=safe_extract_outputs,
        ),
        max_retries=1
    )

###############################################################################
# Prompt

@mcp.prompt()
async def jupyter_cite(
    prompt: Annotated[str, Field(description="User prompt for the cited cells")],
    cell_indices: Annotated[str, Field(description="Cell indices to cite (0-based),supporting flexible range format, e.g., '0,1,2', '0-2' or '0-2,4'")],
    notebook_name: Annotated[str, Field(description="Name of the notebook to cite cells from, default (empty) to current activated notebook")] = "",
):
    """
    Like @ or # in Coding IDE or CLI, cite specific cells from specified notebook and insert them into the prompt.
    """
    return await safe_notebook_operation(
        lambda: JupyterCitePrompt().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            notebook_manager=notebook_manager,
            cell_indices=cell_indices,
            notebook_name=notebook_name,
            prompt=prompt,
        )
    )

###############################################################################
# Helper Functions for Extension.


async def get_registered_tools():
    """
    Get list of all registered MCP tools with their metadata.
    
    This function is used by the Jupyter extension to dynamically expose
    the tool registry without hardcoding tool names and parameters.
    
    For JUPYTER_SERVER mode, it queries the jupyter-mcp-tools extension.
    For MCP_SERVER mode, it uses the local FastMCP registry.
    
    Returns:
        list: List of tool dictionaries with name, description, and inputSchema
    """
    context = ServerContext.get_instance()
    mode = context._mode
    
    # For JUPYTER_SERVER mode, expose BOTH FastMCP tools AND jupyter-mcp-tools (when enabled)
    if mode == ServerMode.JUPYTER_SERVER:
        all_tools = []
        jupyter_tool_names = set()
        
        # Check if JupyterLab mode is enabled before loading jupyter-mcp-tools
        if server_context.is_jupyterlab_mode():
            logger.info("JupyterLab mode enabled, loading selected jupyter-mcp-tools")
            
            # Get tools from jupyter-mcp-tools extension
            try:
                from jupyter_mcp_tools import get_tools
                
                # Get the base_url and token from server context
                # In JUPYTER_SERVER mode, we should use the actual serverapp URL, not hardcoded localhost
                if server_context.serverapp is not None:
                    # Use the actual Jupyter server connection URL
                    base_url = server_context.serverapp.connection_url
                    token = server_context.serverapp.token
                    logger.info(f"Using Jupyter ServerApp connection URL: {base_url}")
                else:
                    # Fallback to configuration (for remote scenarios)
                    config = get_config()
                    base_url = config.runtime_url if config.runtime_url else "http://localhost:8888"
                    token = config.runtime_token
                    logger.info(f"Using config runtime URL: {base_url}")
                
                logger.info(f"Querying jupyter-mcp-tools at {base_url}")
                
                # Define specific tools we want to load from jupyter-mcp-tools
                allowed_jupyter_tools = [
                    "notebook_run-all-cells",  # Run all cells in current notebook  
                ]
                
                # Try querying with broader terms since specific IDs don't work
                try:
                    search_query = ",".join(allowed_jupyter_tools)
                    logger.info(f"Searching jupyter-mcp-tools with query: '{search_query}' (allowed_tools: {allowed_jupyter_tools})")
                    
                    tools_data = await get_tools(
                        base_url=base_url,
                        token=token,
                        query=search_query,
                        enabled_only=False
                    )
                    logger.info(f"Query returned {len(tools_data)} tools")
                    
                    # Use the tools directly since query should return only what we want
                    for tool in tools_data:
                        logger.info(f"Found tool: {tool.get('id', '')}")
                    
                except Exception as e:
                    logger.warning(f"Failed to load jupyter-mcp-tools: {e}")
                    tools_data = []
                
                logger.info(f"Successfully loaded {len(tools_data)} specific jupyter-mcp-tools")
                
                logger.info(f"Retrieved {len(tools_data)} tools from jupyter-mcp-tools extension")
                
                # Convert jupyter-mcp-tools format to MCP format
                for tool_data in tools_data:
                    tool_name = tool_data.get('id', '')
                    jupyter_tool_names.add(tool_name)
                    
                    # Only include MCP protocol fields (exclude internal fields like commandId)
                    tool_dict = {
                        "name": tool_name,
                        "description": tool_data.get('caption', tool_data.get('label', '')),
                    }
                    
                    # Convert parameters to inputSchema
                    # The parameters field contains the JSON Schema for the tool's arguments
                    params = tool_data.get('parameters', {})
                    if params and isinstance(params, dict) and params.get('properties'):
                        # Tool has parameters - use them as inputSchema
                        tool_dict["inputSchema"] = params
                        tool_dict["parameters"] = list(params['properties'].keys())
                        logger.debug(f"Tool {tool_dict['name']} has parameters: {tool_dict['parameters']}")
                    else:
                        # Tool has no parameters - use empty schema
                        tool_dict["parameters"] = []
                        tool_dict["inputSchema"] = {
                            "type": "object",
                            "properties": {},
                            "description": tool_data.get('usage', '')
                        }
                    
                    all_tools.append(tool_dict)
                
                logger.info(f"Converted {len(all_tools)} tool(s) from jupyter-mcp-tools with parameter schemas")
                
            except Exception as e:
                logger.error(f"Error querying jupyter-mcp-tools extension: {e}", exc_info=True)
                # Continue to add FastMCP tools even if jupyter-mcp-tools fails
        else:
            logger.info("JupyterLab mode disabled, skipping jupyter-mcp-tools integration")
        
        # Second, add FastMCP tools (excluding duplicates)
        # Map FastMCP tool names to their jupyter-mcp-tools equivalents
        fastmcp_to_jupyter_mapping = {
            # Add mappings as needed when tools overlap
        }
        
        try:
            tools_list = await mcp.list_tools()
            logger.info(f"Retrieved {len(tools_list)} tools from FastMCP registry")
            
            for tool in tools_list:
                # Check if this FastMCP tool has a jupyter-mcp-tools equivalent
                jupyter_equivalent = fastmcp_to_jupyter_mapping.get(tool.name)
                
                if jupyter_equivalent and jupyter_equivalent in jupyter_tool_names:
                    logger.info(f"Skipping FastMCP tool '{tool.name}' - equivalent '{jupyter_equivalent}' available from jupyter-mcp-tools")
                    continue
                
                # Add FastMCP tool
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
                
                all_tools.append(tool_dict)
            
            logger.info(f"Added {len(all_tools) - len(jupyter_tool_names)} FastMCP tool(s), total: {len(all_tools)}")
            
        except Exception as e:
            logger.error(f"Error retrieving FastMCP tools: {e}", exc_info=True)
        
        return all_tools
    
    # For MCP_SERVER mode, use local FastMCP registry
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
        
        # Include full outputSchema for MCP protocol compatibility
        if hasattr(tool, 'outputSchema') and tool.outputSchema:
            tool_dict["outputSchema"] = tool.outputSchema
        else:
            tool_dict["outputSchema"] = []
        
        tools.append(tool_dict)
    
    return tools