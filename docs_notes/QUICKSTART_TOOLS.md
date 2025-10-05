<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Quick Start Guide - Using Tool Classes

## What's Been Done (8/18 tools)

You now have **8 tools** extracted into separate class files in `jupyter_mcp_server/tools/`:

### ✅ Notebook Management (5 tools)
- `list_notebook.py` - List all notebooks (with async local API support)
- `connect_notebook_tool.py` - Connect to/create notebooks (dual-mode)
- `restart_notebook_tool.py` - Restart notebook kernel
- `disconnect_notebook_tool.py` - Disconnect from notebook
- `switch_notebook_tool.py` - Switch active notebook

### ✅ Cell Reading (3 tools)
- `read_all_cells_tool.py` - Read all cells
- `list_cell_tool.py` - List cell information
- `read_cell_tool.py` - Read specific cell

## How to Use These Tools

### Option 1: Use Existing Tool Registry (Recommended)

```python
from jupyter_mcp_server.tools import (
    ListNotebookTool,
    ConnectNotebookTool,
    ToolRegistry
)
from jupyter_mcp_server.config import get_config

# Create registry and register tools
registry = ToolRegistry()
registry.register(ListNotebookTool())
registry.register(ConnectNotebookTool())

# Detect mode and create clients
config = get_config()
mode, clients = registry.detect_mode_and_create_clients(config)

# Execute a tool
list_tool = registry.get_tool("list_notebook")
result = await list_tool.execute(
    mode=mode,
    **clients,
    notebook_manager=notebook_manager
)
```

### Option 2: Use Tools Directly

```python
from jupyter_mcp_server.tools import ListNotebookTool, ServerMode
from jupyter_mcp_server.config import get_config

# Create tool instance
tool = ListNotebookTool()

# Execute with explicit mode and clients
result = await tool.execute(
    mode=ServerMode.JUPYTER_SERVER,
    contents_manager=contents_manager,
    notebook_manager=notebook_manager
)
```

## Remaining Work (10/18 tools)

### Cell Writing Tools (4 tools) - Pattern Available
These follow the same pattern as cell reading tools but modify the notebook:
- `insert_cell_tool.py` - Insert cell at position
- `insert_execute_code_cell_tool.py` - Insert and execute code cell
- `overwrite_cell_source_tool.py` - Overwrite cell content
- `delete_cell_tool.py` - Delete specific cell

**Pattern**: Use `notebook_manager.get_current_connection()` like read tools

### Cell Execution Tools (3 tools) - Need Kernel Support
These execute code and need kernel management:
- `execute_cell_simple_timeout_tool.py` - Execute with timeout
- `execute_cell_streaming_tool.py` - Execute with streaming progress
- `execute_cell_with_progress_tool.py` - Execute with progress updates

**Pattern**: Use `notebook_manager.get_kernel()` + kernel execution

### Other Tools (3 tools) - Need Dual-Mode Support
These interact with Jupyter Server and need local API support:
- `execute_ipython_tool.py` - Execute IPython code directly
- `list_all_files_tool.py` - List all files (needs `contents_manager`)
- `list_kernel_tool.py` - List kernels (needs `kernel_manager`)

**Pattern**: Dual-mode with local kernel_manager/contents_manager

## Creating New Tools

1. **Copy an existing tool file** as template (e.g., `read_cell_tool.py`)
2. **Update class name** (e.g., `DeleteCellTool`)
3. **Update properties**: `name` and `description`
4. **Implement `execute()` method**:
   - Add tool-specific parameters
   - Implement logic using provided clients/managers
   - Handle mode differences if needed
5. **Add import to `tools/__init__.py`**
6. **Test imports**: `python -c "from jupyter_mcp_server.tools import DeleteCellTool"`

## Testing Tools

### Test Individual Tool Import
```bash
python -c "from jupyter_mcp_server.tools import ListNotebookTool; print('✅ OK')"
```

### Test All Current Tools
```bash
python -c "from jupyter_mcp_server.tools import \
ListNotebookTool, ConnectNotebookTool, RestartNotebookTool, \
DisconnectNotebookTool, SwitchNotebookTool, ReadAllCellsTool, \
ListCellTool, ReadCellTool; print('✅ All 8 tools OK')"
```

## Integration with server.py

After all tools are created, update `server.py`:

```python
# At top of server.py
from jupyter_mcp_server.tools import (
    ListNotebookTool,
    ConnectNotebookTool,
    # ... all other tools
)
from jupyter_mcp_server.tools.registry import ToolRegistry

# Create and populate registry
tool_registry = ToolRegistry()
tool_registry.register(ListNotebookTool())
tool_registry.register(ConnectNotebookTool())
# ... register all tools

# Replace @mcp.tool() functions with registry calls
@mcp.tool()
async def list_notebook() -> str:
    """List all notebooks..."""
    config = get_config()
    mode, clients = tool_registry.detect_mode_and_create_clients(config)
    tool = tool_registry.get_tool("list_notebook")
    return await tool.execute(mode, **clients, notebook_manager=notebook_manager)
```

## Benefits You Get

1. **✅ Mode Detection**: Automatic HTTP vs local API selection
2. **✅ Type Safety**: Full type hints throughout
3. **✅ Testing**: Each tool can be tested independently
4. **✅ Organization**: One file per tool, easy to find and modify
5. **✅ Reusability**: Tools can be used outside MCP server context
6. **✅ Documentation**: Self-contained docstrings
7. **✅ Async Support**: Proper async/await for local Jupyter Server API

## Key Async Pattern

**IMPORTANT**: Jupyter Server's local API is async!

```python
# ❌ Wrong (will get RuntimeWarning)
model = contents_manager.get(path)

# ✅ Correct
model = await contents_manager.get(path)
```

All local API methods need `await`:
- `await contents_manager.get(path, content=True)`
- `await contents_manager.save(model, path)`
- `await kernel_manager.start_kernel(...)`

HTTP API is synchronous (no await needed):
- `model = server_client.contents.get(path)` ✅
- `kernel_client.start()` ✅

## Next Steps

1. **Create remaining 10 tool files** using existing tools as templates
2. **Update `tools/__init__.py`** to export new tools
3. **Test imports** for each new tool
4. **Update `server.py`** to use tool registry
5. **Test both modes**: `make start` (HTTP) and `make start-as-jupyter-server` (local)

## Reference Files

- **Pattern Examples**: `jupyter_mcp_server/tools/list_notebook.py` (dual-mode with async)
- **Simple Pattern**: `jupyter_mcp_server/tools/read_cell_tool.py` (mode-agnostic)
- **Documentation**: `jupyter_mcp_server/tools/EXTRACTION_PROGRESS.md`
- **Status**: `TOOL_EXTRACTION_STATUS.md` (this directory root)

---

**Current Progress**: 8/18 tools (44% complete)  
**All Imports Working**: ✅  
**Ready for**: Creating remaining 10 tools
