<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Tool Extraction Progress

This document tracks the migration of `@mcp.tool()` functions from `server.py` into separate tool class files in the `tools/` package.

## Completed Tool Files ✅

### Notebook Management Tools (4/4)
- ✅ `tools/list_notebook.py` - ListNotebookTool (has async local API support)
- ✅ `tools/use_notebook_tool.py` - ConnectNotebookTool (dual-mode with local API)
- ✅ `tools/restart_notebook_tool.py` - RestartNotebookTool (mode-agnostic)
- ✅ `tools/disconnect_notebook_tool.py` - DisconnectNotebookTool (mode-agnostic)
- ✅ `tools/switch_notebook_tool.py` - SwitchNotebookTool (mode-agnostic)

## Remaining Tools to Extract (13 tools)

### Cell Reading Tools (3 tools)
- [ ] `read_all_cells_tool.py` - ReadAllCellsTool
  - Uses: `notebook_manager.get_current_connection()`
  - Needs: Local contents_manager support for reading notebook
  
- [ ] `list_cell_tool.py` - ListCellTool
  - Uses: `notebook_manager.get_current_connection()`
  - Needs: Local contents_manager support
  
- [ ] `read_cell_tool.py` - ReadCellTool  
  - Uses: `notebook_manager.get_current_connection()`
  - Needs: Local contents_manager support

### Cell Writing Tools (4 tools)
- [ ] `insert_cell_tool.py` - InsertCellTool
  - Uses: `notebook_manager.get_current_connection()`
  - Needs: Local contents_manager support for saving
  
- [ ] `insert_execute_code_cell_tool.py` - InsertExecuteCodeCellTool
  - Uses: `notebook_manager.get_current_connection()` + kernel
  - Needs: Local contents_manager + kernel_manager support
  
- [ ] `overwrite_cell_source_tool.py` - OverwriteCellSourceTool
  - Uses: `notebook_manager.get_current_connection()`
  - Needs: Local contents_manager support
  
- [ ] `delete_cell_tool.py` - DeleteCellTool
  - Uses: `notebook_manager.get_current_connection()`
  - Needs: Local contents_manager support

### Cell Execution Tools (3 tools)
- [ ] `execute_cell_simple_timeout_tool.py` - ExecuteCellSimpleTimeoutTool
  - Uses: `notebook_manager.get_current_connection()` + kernel
  - Needs: Local kernel_manager support
  
- [ ] `execute_cell_streaming_tool.py` - ExecuteCellStreamingTool
  - Uses: `notebook_manager.get_current_connection()` + kernel
  - Needs: Local kernel_manager support
  
- [ ] `execute_cell_with_progress_tool.py` - ExecuteCellWithProgressTool
  - Uses: `notebook_manager.get_current_connection()` + kernel
  - Needs: Local kernel_manager support

### Other Tools (3 tools)
- [ ] `execute_ipython_tool.py` - ExecuteIPythonTool
  - Uses: `notebook_manager.get_kernel()` + kernel execution
  - Needs: Local kernel_manager support
  
- [ ] `list_all_files_tool.py` - ListAllFilesTool
  - Uses: `JupyterServerClient` for file listing
  - Needs: Local contents_manager support
  
- [ ] `list_kernel_tool.py` - ListKernelTool
  - Uses: `JupyterServerClient` for kernel listing
  - Needs: Local kernel_manager support

## Pattern for Each Tool

Each tool file should follow this structure:

```python
# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""<Tool name> tool implementation."""

from typing import Any, Optional, List, Union, Literal
from jupyter_server_api import JupyterServerClient
from jupyter_kernel_client import KernelClient
from jupyter_mcp_server.tools.base import BaseTool, ServerMode
from jupyter_mcp_server.notebook_manager import NotebookManager
from mcp.types import ImageContent


class MyTool(BaseTool):
    """Tool to <description>."""
    
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return """<Full description>
    
Args:
    param1: Description
    
Returns:
    type: Description"""
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        kernel_client: Optional[Any] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        # Tool-specific parameters
        param1: str = None,
        **kwargs
    ) -> str:
        """Execute the tool.
        
        Args:
            mode: Server mode (MCP_SERVER or JUPYTER_SERVER)
            server_client: HTTP client for MCP_SERVER mode
            contents_manager: Direct API for JUPYTER_SERVER mode
            notebook_manager: Notebook manager instance
            param1: Tool parameter
            **kwargs: Additional parameters
            
        Returns:
            Tool result
        """
        # Implementation with mode detection
        if mode == ServerMode.JUPYTER_SERVER and contents_manager is not None:
            # Use local API
            result = await contents_manager.get(...)
        elif mode == ServerMode.MCP_SERVER and server_client is not None:
            # Use HTTP API
            result = server_client.contents.get(...)
        else:
            raise ValueError(f"Invalid mode or missing clients: mode={mode}")
        
        return result
```

## Integration with server.py

After creating tool files, update `server.py` to use tool classes:

```python
# Import tool classes
from jupyter_mcp_server.tools import (
    ListNotebookTool,
    ConnectNotebookTool,
    # ... other tools
)

# Create tool registry
from jupyter_mcp_server.tools.registry import ToolRegistry
tool_registry = ToolRegistry()

# Register tools
tool_registry.register(ListNotebookTool())
tool_registry.register(ConnectNotebookTool())
# ... register other tools

# Replace @mcp.tool() decorators with calls to registry
@mcp.tool()
async def list_notebook() -> str:
    """List all notebooks..."""
    config = get_config()
    mode, clients = tool_registry.detect_mode_and_create_clients(config)
    tool = tool_registry.get_tool("list_notebook")
    return await tool.execute(mode, **clients, notebook_manager=notebook_manager)
```

## Benefits of This Approach

1. **Clear Separation**: Each tool in its own file for better organization
2. **Mode Detection**: Built-in dual-mode support (HTTP vs local API)
3. **Testability**: Easier to unit test individual tools
4. **Reusability**: Tools can be used outside of MCP server context
5. **Maintainability**: Changes to one tool don't affect others
6. **Documentation**: Self-contained with type hints and docstrings

## Next Steps

1. Create remaining 13 tool files following the pattern
2. Update `tools/__init__.py` to export all tool classes
3. Update `server.py` to use tool registry
4. Test all tools in both MCP_SERVER and JUPYTER_SERVER modes
5. Remove old inline tool implementations from `server.py`
