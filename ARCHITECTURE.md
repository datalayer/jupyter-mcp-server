<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Jupyter MCP Server - Architecture

## Overview

The Jupyter MCP Server supports **dual-mode operation**:

1. **MCP_SERVER Mode** (Standalone) - Connects to remote Jupyter servers via HTTP/WebSocket
2. **JUPYTER_SERVER Mode** (Extension) - Runs embedded in Jupyter Server with direct API access

Both modes share the same tool implementations, with automatic backend selection based on configuration.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       MCP Client                                 │
│            (Claude Desktop, VS Code, Cursor, etc.)              │
└────────────┬────────────────────────────────────┬───────────────┘
             │                                    │
             │ stdio/SSE                          │ HTTP/SSE
             │                                    │
    ┌────────▼────────────┐          ┌───────────▼──────────────┐
    │   MCP_SERVER Mode   │          │  JUPYTER_SERVER Mode     │
    │   (Standalone)      │          │  (Extension)             │
    │                     │          │                          │
    │  FastMCP Server     │          │  Tornado Handlers        │
    │  (server.py)        │          │  (handlers.py)           │
    └──────────┬──────────┘          └──────────┬───────────────┘
               │                                │
               │ Tool Call                      │ Tool Call
               │                                │
        ┌──────▼────────────────────────────────▼──────┐
        │              Tool Layer                      │
        │  (18 tools in jupyter_mcp_server/tools/)    │
        │                                              │
        │  Each tool implements dual-mode logic:       │
        │  - _operation_http() for MCP_SERVER         │
        │  - _operation_local() for JUPYTER_SERVER    │
        └──────────┬───────────────────────┬───────────┘
                   │                       │
                   │ Mode Selection        │
                   │                       │
          ┌────────▼────────┐     ┌────────▼────────┐
          │ Remote Backend  │     │  Local Backend  │
          │                 │     │                 │
          │ - JupyterServer │     │ - contents_     │
          │   Client (HTTP) │     │   manager       │
          │ - KernelClient  │     │ - kernel_       │
          │   (WebSocket)   │     │   manager       │
          │ - NbModelClient │     │ - kernel_spec_  │
          │   (WebSocket)   │     │   manager       │
          └────────┬────────┘     └────────┬────────┘
                   │                       │
                   │ HTTP/WS               │ Direct Python API
                   │                       │
            ┌──────▼──────────┐   ┌───────▼────────┐
            │ Remote Jupyter  │   │ Local Jupyter  │
            │ Server          │   │ Server         │
            └─────────────────┘   └────────────────┘
```

## Core Components

### 1. Tool Layer (`jupyter_mcp_server/tools/`)

**BaseTool** - Abstract base class for all tools:
```python
class BaseTool:
    @property
    def name(self) -> str: ...
    
    @property
    def description(self) -> str: ...
    
    async def execute(
        self,
        mode: ServerMode,
        server_client: Optional[JupyterServerClient] = None,
        contents_manager: Optional[Any] = None,
        kernel_manager: Optional[Any] = None,
        kernel_spec_manager: Optional[Any] = None,
        notebook_manager: Optional[NotebookManager] = None,
        **kwargs
    ) -> Any: ...
```

**Tool Categories** (18 tools total):
- **Notebook Management** (5): list_notebook, use_notebook, unuse_notebook, restart_notebook
- **Cell Reading** (3): read_cells, list_cells, read_cell
- **Cell Writing** (4): insert_cell, insert_execute_code_cell, overwrite_cell_source, delete_cell
- **Cell Execution** (3): execute_cell_simple_timeout, execute_cell_streaming, execute_cell_with_progress
- **Other** (3): execute_ipython, list_files, list_kernels

**Dual-Mode Implementation Pattern**:
```python
async def execute(self, mode, server_client, contents_manager, **kwargs):
    if mode == ServerMode.JUPYTER_SERVER and contents_manager:
        # Local mode: direct API access
        return await self._operation_local(contents_manager, ...)
    elif mode == ServerMode.MCP_SERVER and server_client:
        # Remote mode: HTTP requests
        return await self._operation_http(server_client, ...)
    else:
        raise ValueError(f"Invalid mode or missing clients")
```

### 2. Server Context (`server.py::ServerContext`)

**Purpose**: Singleton managing server mode and providing access to Jupyter managers.

```python
class ServerContext:
    _instance = None
    _mode: Optional[ServerMode] = None
    _server_client: Optional[JupyterServerClient] = None
    _contents_manager: Optional[Any] = None
    _kernel_manager: Optional[Any] = None
    _kernel_spec_manager: Optional[Any] = None
    
    @classmethod
    def get_instance(cls) -> "ServerContext":
        """Get or create singleton instance."""
        
    def initialize(self, mode: ServerMode, **managers):
        """Initialize context with mode and managers."""
```

**Mode Detection**:
- **JUPYTER_SERVER**: When running as extension, serverapp available
- **MCP_SERVER**: When running standalone, connects via HTTP

### 3. FastMCP Server (`server.py`)

**Role**: Main entry point for MCP_SERVER mode, tool registry, and @mcp.tool() wrappers.

```python
mcp = FastMCPWithCORS(name="Jupyter MCP Server", ...)
notebook_manager = NotebookManager()

# Tool wrappers delegate to tool.execute()
@mcp.tool()
async def list_notebook() -> str:
    server_context = ServerContext.get_instance()
    return await list_notebook_tool.execute(
        mode=server_context.mode,
        server_client=server_context.server_client,
        contents_manager=server_context.contents_manager,
        notebook_manager=notebook_manager,
    )
```

**Dynamic Tool Registry** (`get_registered_tools()`):
- Queries FastMCP's `list_tools()` to get all registered tools
- Returns tool metadata (name, description, parameters, inputSchema)
- Used by Jupyter extension to expose tools without hardcoding

### 4. Jupyter Extension (`jupyter_extension/`)

**Extension App** (`extension.py::JupyterMCPServerExtensionApp`):
```python
class JupyterMCPServerExtensionApp(ExtensionApp):
    name = "jupyter_mcp_server"
    
    # Configuration traits
    document_url = Unicode("local", config=True)
    runtime_url = Unicode("local", config=True)
    document_id = Unicode("notebook.ipynb", config=True)
    
    def initialize_settings(self):
        # Store config in Tornado settings
        # Initialize ServerContext with JUPYTER_SERVER mode
```

**Handlers** (`handlers.py`):
- `MCPHealthHandler`: GET /mcp/healthz
- `MCPToolsListHandler`: GET /mcp/tools/list (uses `get_registered_tools()`)
- `MCPToolsCallHandler`: POST /mcp/tools/call
- `MCPSSEHandler`: SSE endpoint for MCP protocol

**Extension Context** (`context.py::ServerContext`):
```python
class ServerContext:
    _serverapp: Optional[Any] = None
    _context_type: str = "unknown"
    
    def update(self, context_type: str, serverapp: Any):
        """Called by extension to register serverapp."""
    
    def is_local_document(self) -> bool:
        """Check if document operations use local access."""
    
    def get_contents_manager(self):
        """Get local contents_manager from serverapp."""
```

### 5. Notebook Manager (`notebook_manager.py`)

**Purpose**: Manages notebook connections and kernel lifecycle.

**Key Features**:
- Tracks managed notebooks with kernel associations
- Supports both local (JUPYTER_SERVER) and remote (MCP_SERVER) modes
- Provides `NotebookConnection` context manager for Y.js document access

**Local vs Remote**:
- **Local mode**: Notebooks tracked with `is_local=True`, no WebSocket connections
- **Remote mode**: Establishes WebSocket connections via `NbModelClient`

```python
class NotebookManager:
    def add_notebook(self, name, kernel, server_url="local", ...):
        """Add notebook with mode detection (local vs remote)."""
    
    def get_current_connection(self):
        """Get WebSocket connection (MCP_SERVER mode only)."""
```

## Configuration

### MCP_SERVER Mode (Standalone)

**Start Command**:
```bash
jupyter-mcp-server start \
  --transport streamable-http \
  --document-url http://localhost:8888 \
  --runtime-url http://localhost:8888 \
  --document-token MY_TOKEN \
  --runtime-token MY_TOKEN \
  --port 4040
```

**Behavior**:
- ServerContext initialized with `mode=ServerMode.MCP_SERVER`
- Tools use `JupyterServerClient` for HTTP requests
- Notebook connections use `NbModelClient` for WebSocket (Y.js documents)

### JUPYTER_SERVER Mode (Extension)

**Start Command**:
```bash
jupyter server \
  --JupyterMCPServerExtensionApp.document_url=local \
  --JupyterMCPServerExtensionApp.runtime_url=local \
  --JupyterMCPServerExtensionApp.document_id=notebook.ipynb
```

**Configuration File** (`jupyter_server_config.py`):
```python
c.ServerApp.jpserver_extensions = {"jupyter_mcp_server": True}
c.JupyterMCPServerExtensionApp.document_url = "local"
c.JupyterMCPServerExtensionApp.runtime_url = "local"
```

**Behavior**:
- Extension auto-enabled (via `jupyter-config/` file)
- ServerContext updated with `mode=ServerMode.JUPYTER_SERVER`
- Tools use `contents_manager`, `kernel_manager` directly
- Cell reading tools parse notebook JSON from file system

## Request Flow Examples

### Example 1: List Notebooks (JUPYTER_SERVER Mode)

```
MCP Client
  → POST /mcp/tools/call {"tool_name": "list_notebooks"}
    → MCPSSEHandler (or MCPToolsCallHandler)
      → FastMCP calls @mcp.tool() wrapper
        → list_notebook_tool.execute(
            mode=JUPYTER_SERVER,
            contents_manager=serverapp.contents_manager
          )
          → _list_notebooks_local(contents_manager)
            → contents_manager.get("", content=True, type='directory')
              → Direct file system access (no HTTP)
            ← List of .ipynb files
          ← Formatted table
        ← Tool result
      ← JSON-RPC response
    ← SSE message
  ← Tool result displayed
```

### Example 2: List Cells (JUPYTER_SERVER Mode)

```
MCP Client
  → POST /mcp/tools/call {"tool_name": "list_cells"}
    → FastMCP calls list_cells() wrapper
      → list_cells_tool.execute(
          mode=JUPYTER_SERVER,
          contents_manager=serverapp.contents_manager
        )
        → _list_cells_local(contents_manager, "notebook.ipynb")
          → contents_manager.get("notebook.ipynb", content=True, type='notebook')
            → Read notebook JSON from file
          ← Notebook content (cells array)
        → Format cells into table
        ← Formatted table
      ← Tool result
    ← JSON-RPC response
  ← Cell list displayed
```

### Example 3: Execute Cell (MCP_SERVER Mode)

```
MCP Client
  → Call execute_cell_simple_timeout tool
    → FastMCP calls wrapper
      → execute_cell_simple_timeout_tool.execute(
          mode=MCP_SERVER,
          server_client=JupyterServerClient(...),
          kernel_client=KernelClient(...)
        )
        → Get notebook connection via notebook_manager
          → NbModelClient establishes WebSocket to Y.js document
          → Update cell source in Y.js document
        → kernel_client.execute(code)
          → HTTP/WebSocket to remote kernel
        ← Execution outputs
      ← Tool result
    ← Response
  ← Outputs displayed
```

## Tool Implementation Details

### Cell Reading Tools (read_cells, list_cells, read_cell)

**JUPYTER_SERVER Mode**:
- Read notebook file via `contents_manager.get(path, content=True, type='notebook')`
- Parse JSON structure directly (no Y.js)
- Extract cells, execution counts, outputs from notebook JSON
- Format as needed for tool response

**MCP_SERVER Mode**:
- Establish WebSocket connection via `notebook_manager.get_current_connection()`
- Access Y.js document (`notebook._doc._ycells`)
- Use `CellInfo.from_cell()` to extract structured data
- Supports real-time collaborative editing

### Notebook Listing Tools (list_notebook)

**JUPYTER_SERVER Mode**:
- Recursively traverse directories via `contents_manager.get(path, type='directory')`
- Filter `.ipynb` files
- Match against managed notebooks in `notebook_manager`
- Return TSV-formatted table

**MCP_SERVER Mode**:
- HTTP GET to `/api/contents/` endpoint
- Recursively fetch directory contents
- Same formatting logic

### Kernel Tools (list_kernels, execute_ipython)

**JUPYTER_SERVER Mode**:
- Direct access to `kernel_manager.list_kernels()`
- Direct access to `kernel_spec_manager.get_all_specs()`
- No network overhead

**MCP_SERVER Mode**:
- HTTP GET to `/api/kernels/` and `/api/kernelspecs/`
- Parse JSON responses

## Performance Characteristics

**JUPYTER_SERVER Mode Advantages**:
- **No network latency**: Direct Python function calls
- **No HTTP overhead**: No serialization/deserialization
- **Efficient file access**: Direct file system I/O
- **Real-time updates**: Event-driven via serverapp

**Expected Performance** (Local vs Remote):
- List notebooks: **10-50x faster**
- Read cells: **5-20x faster**
- List kernels: **10-30x faster**
- Execute cells: Similar (kernel execution dominates)

## Design Patterns

### 1. Singleton Pattern
- **ServerContext**: Single instance managing global state
- Thread-safe initialization
- Mode and manager lifecycle

### 2. Strategy Pattern
- **Tool.execute()**: Selects strategy based on `mode`
- `_operation_local()` vs `_operation_http()`
- Transparent to MCP client

### 3. Template Method Pattern
- **BaseTool**: Defines `execute()` interface
- Subclasses implement specific operations
- Consistent parameter passing

### 4. Context Manager Pattern
- **NotebookConnection**: Manages WebSocket lifecycle
- Automatic connection/disconnection
- Resource cleanup

## Tool Registration Flow

```
1. Server startup (server.py)
   ↓
2. Create tool instances (list_notebook_tool = ListNotebooksTool())
   ↓
3. Define @mcp.tool() wrappers
   ↓
4. FastMCP registers tools internally
   ↓
5. get_registered_tools() queries FastMCP
   ↓
6. Extension handlers use get_registered_tools()
   ↓
7. Dynamic tool list exposed via /mcp/tools/list
```

## Error Handling

**Connection Errors** (MCP_SERVER mode):
- `safe_notebook_operation()` wrapper with retries
- Detects WebSocket/HTTP failures
- Automatic reconnection attempts

**Validation Errors**:
- Pydantic models validate tool parameters
- Cell index bounds checking
- Notebook path validation

**Mode Mismatch**:
```python
if mode == ServerMode.JUPYTER_SERVER and contents_manager is None:
    raise ValueError("JUPYTER_SERVER mode requires contents_manager")
```

## Security Model

**Current Implementation**:
- Relies on Jupyter Server's authentication
- No additional MCP-specific auth
- Single-user mode only
- Token-based access (when configured)

**Scope**:
- Full access to Jupyter Server's file system
- Full access to kernel operations
- No resource limits or quotas

## File Structure

```
jupyter_mcp_server/
├── server.py                   # FastMCP server, tool wrappers, ServerContext
├── config.py                   # Configuration management
├── notebook_manager.py         # Notebook/kernel lifecycle
├── models.py                   # Pydantic models (CellInfo, etc.)
├── utils.py                    # Helper functions
├── tools/
│   ├── __init__.py            # Exports BaseTool, ServerMode
│   ├── _base.py               # BaseTool abstract class
│   ├── list_notebooks_tool.py # List notebooks (dual-mode)
│   ├── use_notebook_tool.py   # Connect/create notebooks
│   ├── list_cells_tool.py      # List cells (dual-mode)
│   ├── read_cells_tool.py # Read all cells (dual-mode)
│   ├── read_cell_tool.py      # Read specific cell (dual-mode)
│   └── ... (15 more tools)
└── jupyter_extension/
    ├── __init__.py
    ├── extension.py           # JupyterMCPServerExtensionApp
    ├── handlers.py            # Tornado HTTP handlers
    └── context.py             # Extension ServerContext
```

## Testing Strategy

### Unit Tests
- Tool implementations with mocked managers
- Mode detection logic
- Pydantic model validation

### Integration Tests
- **MCP_SERVER Mode**: HTTP client → FastMCP → tools → remote Jupyter
- **JUPYTER_SERVER Mode**: HTTP client → handlers → tools → local managers

### Manual Testing
```bash
# Test standalone mode
make start
# Connect MCP client to http://localhost:4040

# Test extension mode
make start-as-jupyter-server
# Connect MCP client to http://localhost:8888/mcp/
```

## Migration Path

### Existing Users (No Changes)
- MCP_SERVER mode is default
- All existing configurations work unchanged
- Gradual adoption of extension mode optional

### New Extension Users
1. Install: `pip install jupyter-mcp-server`
2. Extension auto-enabled
3. Configure `document_url=local` (optional)
4. Start Jupyter Server
5. MCP tools available at `/mcp/` endpoints

## Future Enhancements

1. **Write Operations in JUPYTER_SERVER Mode**: Insert, delete, overwrite cells using `contents_manager`
2. **Session Management**: Persistent state across requests
3. **Multi-user Support**: Isolation and resource limits
4. **Caching Layer**: Reduce repeated file system/HTTP access
5. **WebSocket Protocol**: Native MCP WebSocket support
6. **Resource Monitoring**: Track tool usage and performance

## References

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [Jupyter Server Extension Guide](https://jupyter-server.readthedocs.io/en/latest/developers/extensions.html)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Y.js Collaborative Editing](https://github.com/yjs/yjs)

---

**Version**: 1.0  
**Last Updated**: January 2025  
**Status**: Core implementation complete, cell tools updated for dual-mode support
