# Jupyter MCP Server - Tool Architecture Summary

## What We Built

We've created a new architecture that allows Jupyter MCP Server tools to operate in **two modes**:

1. **MCP_SERVER Mode**: Standalone server using HTTP clients (existing behavior)
2. **JUPYTER_SERVER Mode**: Jupyter extension using direct API access (new capability)

This eliminates unnecessary HTTP overhead when running as a Jupyter Server extension.

## Directory Structure

```
jupyter_mcp_server/
├── tools/
│   ├── __init__.py              # Package exports
│   ├── base.py                  # BaseTool abstract class + ServerMode enum
│   ├── registry.py              # ToolRegistry for managing tool instances
│   ├── integration_example.py   # Example of how to integrate with server.py
│   ├── README.md                # Architecture documentation
│   ├── MIGRATION.md             # Step-by-step migration guide
│   │
│   ├── list_notebook.py         # ✅ Implemented
│   ├── connect_notebook.py      # ✅ Implemented
│   ├── disconnect_notebook.py   # ✅ Implemented
│   │
│   ├── restart_notebook.py      # TODO
│   ├── switch_notebook.py       # TODO
│   ├── read_cells.py            # TODO
│   ├── insert_cell.py           # TODO
│   ├── delete_cell.py           # TODO
│   ├── overwrite_cell.py        # TODO
│   ├── execute_cell_*.py        # TODO (3 execution variants)
│   ├── get_kernel_info.py       # TODO
│   ├── interrupt_kernel.py      # TODO
│   ├── restart_kernel_keep_notebook.py  # TODO
│   ├── list_files.py            # TODO
│   ├── list_kernel.py           # TODO
│   └── manage_notebook_files.py # TODO
```

## Key Components

### 1. `ServerMode` Enum (base.py)

```python
class ServerMode(str, Enum):
    MCP_SERVER = "mcp_server"        # Standalone with HTTP clients
    JUPYTER_SERVER = "jupyter_server" # Extension with direct API access
```

### 2. `BaseTool` Abstract Class (base.py)

All tools inherit from this:

```python
class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name"""
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description"""
    
    @abstractmethod
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,  # For MCP_SERVER
        kernel_client: Optional[KernelClient] = None,         # For MCP_SERVER
        contents_manager: Optional[Any] = None,               # For JUPYTER_SERVER
        kernel_manager: Optional[Any] = None,                 # For JUPYTER_SERVER
        kernel_spec_manager: Optional[Any] = None,            # For JUPYTER_SERVER
        **kwargs  # Tool-specific parameters
    ) -> Any:
        """Execute the tool logic"""
```

### 3. `ToolRegistry` (registry.py)

Manages tool instances and handles mode-specific execution:

```python
registry = get_tool_registry()
registry.register(ListNotebookTool())
registry.set_notebook_manager(notebook_manager)

# Execute a tool
result = await registry.execute_tool(
    "list_notebook",
    mode=ServerMode.JUPYTER_SERVER
)
```

The registry automatically:
- Creates HTTP clients for MCP_SERVER mode
- Gets local managers from ServerContext for JUPYTER_SERVER mode
- Passes the notebook_manager to all tools

### 4. Tool Implementation Pattern

Each tool implements both HTTP and local access paths:

```python
class ListNotebookTool(BaseTool):
    def _list_notebooks_http(self, server_client, ...):
        """Use HTTP API (MCP_SERVER mode)"""
        contents = server_client.contents.list_directory(path)
        # ...
    
    def _list_notebooks_local(self, contents_manager, ...):
        """Use local API (JUPYTER_SERVER mode)"""
        model = contents_manager.get(path, content=True, type='directory')
        # ...
    
    async def execute(self, mode, **kwargs):
        if mode == ServerMode.JUPYTER_SERVER:
            return self._list_notebooks_local(kwargs['contents_manager'])
        else:
            return self._list_notebooks_http(kwargs['server_client'])
```

## Integration with FastMCP

Tools are registered with FastMCP using thin wrapper functions:

```python
# Initialize tools
from jupyter_mcp_server.tools import get_tool_registry, register_tool
from jupyter_mcp_server.tools import ListNotebookTool, ConnectNotebookTool

register_tool(ListNotebookTool())
register_tool(ConnectNotebookTool())
# ... register others

registry = get_tool_registry()
registry.set_notebook_manager(notebook_manager)

# Wrap each tool with @mcp.tool()
@mcp.tool()
async def list_notebook() -> str:
    """List all notebooks..."""
    mode = _get_server_mode()
    return await registry.execute_tool("list_notebook", mode=mode)

@mcp.tool()
async def connect_notebook(notebook_name: str, notebook_path: str, ...) -> str:
    """Connect to a notebook..."""
    mode = _get_server_mode()
    return await registry.execute_tool(
        "connect_notebook",
        mode=mode,
        notebook_name=notebook_name,
        notebook_path=notebook_path,
        # ... other params
    )
```

## Mode Detection

The system automatically detects which mode to use:

```python
def _get_server_mode() -> ServerMode:
    """Determine the current server mode."""
    try:
        from jupyter_mcp_server.jupyter_to_mcp.context import get_server_context
        context = get_server_context()
        
        # Check if running as Jupyter extension with local access
        if (context.context_type == "JUPYTER_SERVER" and 
            context.is_local_document() and 
            context.get_contents_manager() is not None):
            return ServerMode.JUPYTER_SERVER
    except:
        pass
    
    return ServerMode.MCP_SERVER  # Default to standalone mode
```

## Implemented Tools (Examples)

### ✅ ListNotebookTool
- **HTTP Mode**: Uses `server_client.contents.list_directory()`
- **Local Mode**: Uses `contents_manager.get(path, content=True)`
- **Benefit**: Eliminates HTTP calls when running as extension

### ✅ ConnectNotebookTool
- **HTTP Mode**: Uses `server_client` to check paths, `KernelClient` for kernels
- **Local Mode**: Uses `contents_manager.get()` and `kernel_manager.start_kernel()`
- **Benefit**: Direct kernel access without HTTP wrapper

### ✅ DisconnectNotebookTool
- **Both Modes**: Only uses `notebook_manager` (no external API)
- **Benefit**: Shows that simple tools work identically in both modes

## Benefits

### 1. Performance
- **JUPYTER_SERVER mode**: No HTTP overhead, direct API access
- **MCP_SERVER mode**: Unchanged, maintains compatibility

### 2. Maintainability
- Each tool in its own file (~150-200 lines)
- Clear separation of concerns
- Easy to find and modify specific tool

### 3. Testability
- Tools can be unit tested independently
- Mock managers for testing
- Test both modes separately

### 4. Type Safety
- `ServerMode` enum prevents mode confusion
- Type hints throughout
- IDE autocomplete support

### 5. Extensibility
- Easy to add new tools following the pattern
- Registry manages tool instances
- No changes to server.py structure needed

## Migration Status

**Completed:**
- ✅ Tool architecture designed
- ✅ Base classes and registry implemented
- ✅ 3 example tools created (list, connect, disconnect)
- ✅ Documentation written (README.md, MIGRATION.md)
- ✅ Integration example provided

**Remaining Work:**
- 🔲 Migrate remaining ~15 tools to new architecture
- 🔲 Update server.py to use registry (follow MIGRATION.md)
- 🔲 Test all tools in both MCP_SERVER and JUPYTER_SERVER modes
- 🔲 Remove old helper functions from server.py
- 🔲 Clean up imports in server.py

## Next Steps

1. **Continue creating tool classes**: Follow the pattern in `list_notebook.py`, `connect_notebook.py`, `disconnect_notebook.py`

2. **Update server.py**: Replace each `@mcp.tool()` function with a wrapper that calls `registry.execute_tool()`

3. **Test incrementally**: After migrating each tool, test it in both modes

4. **Clean up**: Remove old helper functions and unused imports

5. **Document**: Update main README with new architecture

## Usage Examples

### Standalone MCP Server (HTTP Mode)
```bash
# Start with environment variables or CLI args
export DOCUMENT_URL=http://localhost:8888
export RUNTIME_URL=http://localhost:8888
jupyter-mcp-server start --transport streamable-http

# Tools use server_client and kernel_client (HTTP)
```

### Jupyter Extension (Local Mode)
```bash
# Start Jupyter Lab with extension enabled
jupyter lab

# Configure Claude Desktop to connect to http://localhost:8888/mcp
# Tools use contents_manager and kernel_manager (direct API)
```

## Files to Review

1. **`tools/README.md`**: Architecture overview
2. **`tools/MIGRATION.md`**: Step-by-step migration guide
3. **`tools/base.py`**: Base classes and enums
4. **`tools/registry.py`**: Tool registry implementation
5. **`tools/list_notebook.py`**: Complete example tool
6. **`tools/integration_example.py`**: How to integrate with server.py

## Questions?

Refer to:
- **Architecture**: `tools/README.md`
- **Migration**: `tools/MIGRATION.md`
- **Examples**: `list_notebook.py`, `connect_notebook.py`, `disconnect_notebook.py`
- **Integration**: `integration_example.py`
