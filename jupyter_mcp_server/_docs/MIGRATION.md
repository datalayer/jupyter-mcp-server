# Migration Guide: Refactoring Server.py to Use Tool Classes

This guide explains how to migrate the existing `server.py` to use the new tool architecture.

## Overview

The refactoring separates tool implementations into individual files, each with:
- A class inheriting from `BaseTool`
- An `execute()` method that handles both MCP_SERVER and JUPYTER_SERVER modes
- Clear separation between HTTP-based (remote) and local API access

## Step-by-Step Migration

### Step 1: Initialize Tool Registry (Once)

At the top of `server.py`, after creating the `mcp` and `notebook_manager` instances:

```python
# Import tool infrastructure
from jupyter_mcp_server.tools import (
    get_tool_registry,
    register_tool,
    ListNotebookTool,
    ConnectNotebookTool,
    DisconnectNotebookTool,
    # ... import other tools as they're created
)
from jupyter_mcp_server.tools.base import ServerMode

# Initialize tool registry
def _initialize_tools():
    """Register all tool instances with the registry."""
    register_tool(ListNotebookTool())
    register_tool(ConnectNotebookTool())
    register_tool(DisconnectNotebookTool())
    # ... register other tools

def _get_server_mode() -> ServerMode:
    """Determine which server mode we're running in."""
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

# Call after mcp and notebook_manager are created
_initialize_tools()
registry = get_tool_registry()
registry.set_notebook_manager(notebook_manager)
```

### Step 2: Replace Each @mcp.tool() Function

For each existing tool, replace it with a wrapper that calls the registry:

#### Before (Old Pattern):
```python
@mcp.tool()
async def list_notebook() -> str:
    """List all notebooks..."""
    config = get_config()
    server_client = JupyterServerClient(base_url=config.runtime_url, token=config.runtime_token)
    all_notebooks = _list_notebooks_recursively(server_client)
    # ... rest of implementation
```

#### After (New Pattern):
```python
@mcp.tool()
async def list_notebook() -> str:
    """List all notebooks in the Jupyter server (including subdirectories) and show which ones are managed.
    
    To interact with a notebook, it has to be "managed". If a notebook is not managed, 
    you can connect to it using the `connect_notebook` tool.
    
    Returns:
        str: TSV formatted table with notebook information including management status
    """
    mode = _get_server_mode()
    return await registry.execute_tool("list_notebook", mode=mode)
```

### Step 3: Handle Tool-Specific Parameters

For tools that take parameters, pass them through to `execute_tool()`:

#### Before:
```python
@mcp.tool()
async def connect_notebook(
    notebook_name: str,
    notebook_path: str,
    mode: Literal["connect", "create"] = "connect",
    kernel_id: Optional[str] = None,
) -> str:
    """Connect to a notebook..."""
    # ... implementation
```

#### After:
```python
@mcp.tool()
async def connect_notebook(
    notebook_name: str,
    notebook_path: str,
    mode: Literal["connect", "create"] = "connect",
    kernel_id: Optional[str] = None,
) -> str:
    """Connect to a notebook file or create a new one.
    
    Args:
        notebook_name: Unique identifier for the notebook
        notebook_path: Path to the notebook file, relative to the Jupyter server root
        mode: "connect" to connect to existing, "create" to create new
        kernel_id: Specific kernel ID to use (optional)
        
    Returns:
        str: Success message with notebook information
    """
    server_mode = _get_server_mode()
    return await registry.execute_tool(
        "connect_notebook",
        mode=server_mode,
        notebook_name=notebook_name,
        notebook_path=notebook_path,
        operation_mode=mode,  # Note: renamed to avoid conflict with ServerMode parameter
        kernel_id=kernel_id
    )
```

### Step 4: Remove Helper Functions

Helper functions like `_list_notebooks_recursively()` are moved into the tool classes:
- Remove them from `server.py`
- They're now methods like `_list_notebooks_http()` and `_list_notebooks_local()` in the tool class

### Step 5: Clean Up Imports

After migrating all tools, clean up unused imports from `server.py`:
- Keep: `FastMCP`, `get_config`, `notebook_manager` setup
- Remove: Direct usage of `JupyterServerClient` and `KernelClient` in tool functions
- Remove: Helper functions that were moved into tool classes

## Tool Implementation Checklist

When creating a new tool class, ensure:

- [ ] Inherits from `BaseTool`
- [ ] Implements `name` property
- [ ] Implements `description` property with full docstring
- [ ] Implements `execute()` method with all required parameters
- [ ] Has `_operation_http()` method for MCP_SERVER mode (if needed)
- [ ] Has `_operation_local()` method for JUPYTER_SERVER mode (if needed)
- [ ] Routes correctly based on `mode` parameter in `execute()`
- [ ] Handles all required parameters via `**kwargs`
- [ ] Returns correct type (usually `str` or specific type)
- [ ] Registered in `_initialize_tools()`
- [ ] Imported in `jupyter_mcp_server/tools/__init__.py`
- [ ] Has wrapper function in `server.py` with `@mcp.tool()` decorator

## Testing Migration

After migrating each tool:

1. **Syntax Check**:
   ```bash
   python -m py_compile jupyter_mcp_server/tools/<tool_name>.py
   ```

2. **Test MCP_SERVER Mode**:
   ```bash
   make start  # Start standalone MCP server
   # Test with Claude Desktop or MCP client
   ```

3. **Test JUPYTER_SERVER Mode**:
   ```bash
   make jupyterlab  # Start Jupyter Lab
   # Configure as extension with document_url=local, runtime_url=local
   # Test with Claude Desktop
   ```

4. **Verify No Regressions**:
   - Check all 18 tools are listed
   - Verify tools execute without errors
   - Confirm no HTTP connection errors in JUPYTER_SERVER mode

## Common Issues

### Issue: Parameter Name Conflicts

**Problem**: Tool parameter name conflicts with `mode` parameter (ServerMode enum).

**Solution**: Rename the tool's parameter:
```python
# In tool class
async def execute(self, mode: ServerMode, operation_mode: str, ...):
    # Use operation_mode instead of mode
```

### Issue: Missing notebook_manager

**Problem**: Tool needs access to `notebook_manager` but it's not passed.

**Solution**: The registry automatically provides it:
```python
registry.set_notebook_manager(notebook_manager)  # Do this once
# Tools receive it automatically in execute()
```

### Issue: Import Errors

**Problem**: `ServerContext` not available in MCP_SERVER mode.

**Solution**: Always wrap context imports in try/except:
```python
def _get_server_mode():
    try:
        from jupyter_mcp_server.jupyter_extension.context import get_server_context
        context = get_server_context()
        # Check context
    except (ImportError, Exception):
        pass
    return ServerMode.MCP_SERVER
```

## Benefits of This Architecture

1. **Separation of Concerns**: Each tool in its own file
2. **Dual Mode Support**: Single implementation for both modes
3. **Easier Testing**: Tools can be tested independently
4. **Better Maintainability**: Changes to one tool don't affect others
5. **Performance**: JUPYTER_SERVER mode eliminates HTTP overhead
6. **Type Safety**: ServerMode enum prevents mode confusion

## Rollout Strategy

Migrate tools in phases:

**Phase 1**: Simple tools (no complex logic)
- ✅ `disconnect_notebook`
- ✅ `list_notebook`
- `switch_notebook`
- `restart_notebook`

**Phase 2**: Tools with path/file operations
- ✅ `connect_notebook`
- `manage_notebook_files`
- `list_files`

**Phase 3**: Cell operations
- `read_cells`
- `insert_cell`
- `delete_cell`
- `overwrite_cell`

**Phase 4**: Complex execution tools
- `execute_cell_simple_timeout`
- `execute_cell_streaming`
- `execute_cell_with_progress`

**Phase 5**: Kernel management
- `get_kernel_info`
- `interrupt_kernel`
- `restart_kernel_keep_notebook`

Each phase can be tested independently before moving to the next.
