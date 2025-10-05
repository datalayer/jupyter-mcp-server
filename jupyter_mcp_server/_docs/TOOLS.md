# Tools Architecture

This directory contains the refactored tool implementation for Jupyter MCP Server that supports both standalone MCP server mode and Jupyter Server extension mode.

## Overview

Each tool is implemented as a separate class with an `execute` method that can operate in two modes:
- **MCP_SERVER**: Standalone mode using HTTP clients to connect to Jupyter Server
- **JUPYTER_SERVER**: Extension mode with direct API access to serverapp managers

## Architecture

### Base Classes

**`base.py`**
- `ServerMode`: Enum defining MCP_SERVER and JUPYTER_SERVER modes
- `BaseTool`: Abstract base class that all tools inherit from
  - `execute(mode, ...)`: Abstract method for tool execution
  - `name`: Property returning the tool name
  - `description`: Property returning the tool description

### Tool Registry

**`registry.py`**
- `ToolRegistry`: Manages tool instances and execution
  - `register(tool)`: Register a tool instance
  - `execute_tool(name, mode, **kwargs)`: Execute a tool by name
  - Automatically handles mode-specific client creation
  - Integrates with ServerContext for JUPYTER_SERVER mode

### Tool Implementation Pattern

Each tool file (e.g., `list_notebook.py`, `connect_notebook.py`) contains:

```python
class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "Tool description"
    
    def _operation_http(self, server_client, ...) -> Result:
        """Implementation using HTTP API (MCP_SERVER mode)."""
        # Use server_client, kernel_client for HTTP access
        pass
    
    def _operation_local(self, contents_manager, ...) -> Result:
        """Implementation using local API (JUPYTER_SERVER mode)."""
        # Use contents_manager, kernel_manager for direct access
        pass
    
    async def execute(self, mode, server_client=None, contents_manager=None, ..., **kwargs) -> Result:
        """Main execution logic that routes based on mode."""
        if mode == ServerMode.JUPYTER_SERVER:
            return self._operation_local(contents_manager, ...)
        else:
            return self._operation_http(server_client, ...)
```

## Integration with FastMCP

Tools are registered with FastMCP using wrapper functions (see `integration_example.py`):

```python
# 1. Initialize tools
initialize_tools()
registry = get_tool_registry()
registry.set_notebook_manager(notebook_manager)

# 2. Wrap with @mcp.tool() decorator
@mcp.tool()
async def list_notebook() -> str:
    mode = _get_server_mode()  # Determine current mode
    return await registry.execute_tool("list_notebook", mode=mode)
```

## Mode Detection

The `_get_server_mode()` helper function determines which mode to use:

```python
def _get_server_mode() -> ServerMode:
    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context
        context = get_server_context()
        
        if (context.context_type == "JUPYTER_SERVER" and 
            context.is_local_document() and 
            context.get_contents_manager() is not None):
            return ServerMode.JUPYTER_SERVER
    except:
        pass
    
    return ServerMode.MCP_SERVER
```

## Benefits

1. **Clean Separation**: Each tool is in its own file with clear responsibilities
2. **Dual Mode Support**: Single codebase supports both HTTP and local API access
3. **Type Safety**: ServerMode enum ensures correct mode passing
4. **Testability**: Tools can be tested independently with mocked managers
5. **Maintainability**: Changes to one tool don't affect others
6. **Performance**: JUPYTER_SERVER mode eliminates HTTP overhead

## Tool Categories

### Notebook Management
- `list_notebook.py`: List all notebooks with management status
- `connect_notebook.py`: Connect to or create notebooks
- `disconnect_notebook.py`: Disconnect from notebooks
- `restart_notebook.py`: Restart notebook kernels
- `switch_notebook.py`: Switch active notebook
- `get_current_notebook.py`: Get current notebook info

### Cell Management
- `read_cells.py`: Read cells from notebook
- `insert_cell.py`: Insert new cells
- `delete_cell.py`: Delete cells
- `overwrite_cell.py`: Overwrite cell content
- `notebook_info.py`: Get notebook information

### Cell Execution
- `execute_cell_simple_timeout.py`: Execute with timeout
- `execute_cell_streaming.py`: Execute with streaming output
- `execute_cell_with_progress.py`: Execute with progress updates

### Kernel Management
- `get_kernel_info.py`: Get kernel information
- `interrupt_kernel.py`: Interrupt running kernel
- `restart_kernel_keep_notebook.py`: Restart kernel preserving connection

### File Management
- `list_files.py`: List files in Jupyter server
- `manage_notebook_files.py`: Manage notebook files

## Migration Guide

To add a new tool:

1. Create a new file in `jupyter_mcp_server/tools/`
2. Define a class inheriting from `BaseTool`
3. Implement `name`, `description` properties
4. Implement `execute()` method with both HTTP and local logic
5. Register the tool in `initialize_tools()`
6. Create a wrapper function in server.py with `@mcp.tool()` decorator

## Testing

Tools should be tested in both modes:

```python
# Test MCP_SERVER mode
result = await tool.execute(
    mode=ServerMode.MCP_SERVER,
    server_client=mock_server_client,
    kernel_client=mock_kernel_client
)

# Test JUPYTER_SERVER mode
result = await tool.execute(
    mode=ServerMode.JUPYTER_SERVER,
    contents_manager=mock_contents_manager,
    kernel_manager=mock_kernel_manager
)
```
