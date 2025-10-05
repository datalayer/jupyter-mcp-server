# Jupyter MCP Server - Dual-Mode Architecture

## Overview

The Jupyter MCP Server has been refactored to support **dual-mode operation**:

1. **MCP_SERVER Mode** (Standalone) - Original behavior, 100% backward compatible
2. **JUPYTER_SERVER Mode** (Extension) - New embedded mode running as a Jupyter Server extension

This document describes the architecture, design patterns, and implementation strategy.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         MCP Client                              │
│              (Claude Desktop, VS Code, Cursor)                  │
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
        │           Tool Adapters (Future)             │
        │  (NotebookAdapter, CellAdapter, etc.)        │
        └──────────┬───────────────────────┬───────────┘
                   │                       │
                   │ Backend Selection     │
                   │                       │
          ┌────────▼────────┐     ┌────────▼────────┐
          │ Remote Backend  │     │  Local Backend  │
          │                 │     │                 │
          │ jupyter_        │     │ Direct Access   │
          │ nbmodel_client  │     │ serverapp.      │
          │ kernel_client   │     │ contents_mgr    │
          │ server_api      │     │ kernel_mgr      │
          └────────┬────────┘     └────────┬────────┘
                   │                       │
                   │ HTTP/WS               │ Direct
                   │                       │
            ┌──────▼──────────┐   ┌───────▼────────┐
            │ Remote Jupyter  │   │ Local Jupyter  │
            │ Server          │   │ Server         │
            └─────────────────┘   └────────────────┘
```

## Core Components

### 1. Server Context (`jupyter_to_mcp/context.py`)

**Purpose**: Singleton that tracks execution mode and provides access to server resources.

**Key Features**:
- Tracks whether running in MCP_SERVER or JUPYTER_SERVER mode
- Provides access to serverapp instance (when available)
- Detects "local" configuration for direct serverapp access
- Thread-safe singleton pattern

**API**:
```python
context = get_server_context()
context.update(context_type="JUPYTER_SERVER", serverapp=app)
if context.is_local_document():
    # Use local backend
if context.is_local_runtime():
    # Use local kernel manager
```

### 2. Backend Interface (`jupyter_to_mcp/backends/base.py`)

**Purpose**: Abstract interface defining notebook and kernel operations.

**Implementations**:
- **RemoteBackend**: Uses HTTP/WebSocket clients (jupyter_nbmodel_client, jupyter_kernel_client)
- **LocalBackend**: Direct access to serverapp managers (contents_manager, kernel_manager)

**Operations**:
- Notebook: get_content, list, exists, create
- Cells: read, append, insert, delete, overwrite
- Kernels: execute, interrupt, restart, shutdown, list

### 3. Local Backend (`jupyter_to_mcp/backends/local_backend.py`)

**Purpose**: Efficient local access when running as Jupyter Server extension.

**Key Features**:
- Direct access to `serverapp.contents_manager` for file operations
- Direct access to `serverapp.kernel_manager` for kernel operations
- No network overhead
- Real-time updates via server's internal events

**Example**:
```python
backend = LocalBackend(serverapp)
content = await backend.get_notebook_content("notebook.ipynb")
kernel_id = await backend.get_or_create_kernel("notebook.ipynb")
outputs = await backend.execute_cell("notebook.ipynb", 0, kernel_id)
```

### 4. Remote Backend (`jupyter_to_mcp/backends/remote_backend.py`)

**Purpose**: Connect to remote Jupyter servers (maintains backward compatibility).

**Status**: Structure defined, full implementation to be refactored from existing server.py logic.

### 5. Jupyter Server Extension (`jupyter_to_mcp/extension.py`)

**Purpose**: Expose MCP tools as a Jupyter Server extension.

**Class**: `JupyterMCPServerExtensionApp(ExtensionAppJinjaMixin, ExtensionApp)`

**Lifecycle**:
```python
def initialize_settings(self):
    # Update server context
    # Store configuration in Tornado settings
    
def initialize_handlers(self):
    # Register /mcp/healthz, /mcp/tools/list, /mcp/tools/call, /mcp/sse
    
async def stop_extension(self):
    # Cleanup resources, reset context
```

**Configuration Traits**:
- `document_url`: "local" or "http://..."
- `runtime_url`: "local" or "http://..."
- `document_id`: Default notebook path
- `document_token`, `runtime_token`: For remote access

### 6. MCP Protocol Handlers (`jupyter_to_mcp/handlers.py`)

**Purpose**: Tornado HTTP handlers implementing MCP protocol endpoints.

**Handlers**:
- `MCPHealthHandler`: GET /mcp/healthz
- `MCPToolsListHandler`: GET /mcp/tools/list
- `MCPToolsCallHandler`: POST /mcp/tools/call
- `MCPSSEHandler`: GET /mcp/sse

**Backend Selection**:
```python
def get_backend(self):
    context = get_server_context()
    if context.is_local_document() or context.is_local_runtime():
        return LocalBackend(context.serverapp)
    else:
        return RemoteBackend(...)
```

### 7. Protocol Messages (`jupyter_to_mcp/protocol/messages.py`)

**Purpose**: Pydantic models for consistent API across both modes.

**Key Models**:
- `ToolRequest`, `ToolResponse`
- `NotebookContentRequest`, `NotebookContentResponse`
- `ExecuteCellRequest`, `ExecuteCellResponse`
- `ConnectNotebookRequest`, `ConnectNotebookResponse`

## Configuration

### MCP_SERVER Mode (Standalone)

**Environment Variables**:
```bash
export DOCUMENT_URL="http://localhost:8888"
export DOCUMENT_TOKEN="MY_TOKEN"
export RUNTIME_URL="http://localhost:8888"
export RUNTIME_TOKEN="MY_TOKEN"
```

**Command**:
```bash
jupyter-mcp-server start \
  --transport streamable-http \
  --document-url http://localhost:8888 \
  --runtime-url http://localhost:8888 \
  --port 4040
```

**Behavior**:
- ServerContext initialized with context_type="MCP_SERVER"
- Tools use Remote Backend (even if connecting to localhost)
- 100% backward compatible with existing implementation

### JUPYTER_SERVER Mode with Local Access

**Command**:
```bash
jupyter server \
  --JupyterMCPServerExtensionApp.document_url=local \
  --JupyterMCPServerExtensionApp.runtime_url=local \
  --JupyterMCPServerExtensionApp.document_id=notebook.ipynb \
  --port=4040 \
  --token=MY_TOKEN
```

**Behavior**:
- ServerContext updated to context_type="JUPYTER_SERVER"
- document_url="local" → use Local Backend for notebook operations
- runtime_url="local" → use Local Backend for kernel operations
- MCP endpoints available at http://localhost:4040/mcp/

**Configuration File** (`jupyter_server_config.py`):
```python
c.ServerApp.jpserver_extensions = {"jupyter_mcp_server": True}
c.JupyterMCPServerExtensionApp.document_url = "local"
c.JupyterMCPServerExtensionApp.runtime_url = "local"
```

### JUPYTER_SERVER Mode with Remote Access

**Configuration**:
```python
c.JupyterMCPServerExtensionApp.document_url = "http://other-jupyter:8888"
c.JupyterMCPServerExtensionApp.document_token = "REMOTE_TOKEN"
c.JupyterMCPServerExtensionApp.runtime_url = "http://other-jupyter:8888"
c.JupyterMCPServerExtensionApp.runtime_token = "REMOTE_TOKEN"
```

**Behavior**:
- Running as Jupyter Server extension
- But still uses Remote Backend to connect to another Jupyter server
- Useful for federated deployments

## Request Flow Examples

### Example 1: List Notebooks (Local Mode)

```
MCP Client
  → HTTP GET /mcp/tools/call {"tool_name": "list_notebook"}
    → MCPToolsCallHandler
      → get_backend() → LocalBackend(serverapp)
        → backend.list_notebooks()
          → serverapp.contents_manager.get("")
            → Direct file system access
          ← List of .ipynb files
        ← notebooks list
      ← JSON response
    ← HTTP 200 {"success": true, "result": [...]}
  ← Tool result
```

### Example 2: Execute Cell (Local Mode)

```
MCP Client
  → HTTP POST /mcp/tools/call {"tool_name": "execute_cell", "arguments": {...}}
    → MCPToolsCallHandler
      → get_backend() → LocalBackend(serverapp)
        → backend.execute_cell(path, cell_index, kernel_id)
          → serverapp.kernel_manager.get_kernel(kernel_id)
          → kernel.client().execute(code)
          → Collect outputs from iopub
          ← Cell outputs
        ← outputs
      ← JSON response
    ← HTTP 200 {"success": true, "result": [...]}
  ← Execution outputs
```

### Example 3: Execute Cell (Remote Mode)

```
MCP Client
  → HTTP POST /mcp/tools/call {"tool_name": "execute_cell", "arguments": {...}}
    → MCPToolsCallHandler
      → get_backend() → RemoteBackend(document_url, runtime_url)
        → backend.execute_cell(path, cell_index, kernel_id)
          → jupyter_nbmodel_client.NbModelClient(ws_url)
          → jupyter_kernel_client.KernelClient(server_url)
          → WebSocket connection to remote server
          ← Cell outputs
        ← outputs
      ← JSON response
    ← HTTP 200 {"success": true, "result": [...]}
  ← Execution outputs
```

## Design Patterns

### 1. Singleton Pattern
- **ServerContext**: Global state management
- Thread-safe initialization
- Single source of truth for server mode

### 2. Adapter Pattern (Planned)
- BaseToolAdapter abstract class
- Tool-specific adapters (NotebookAdapter, CellAdapter, KernelAdapter)
- Transparent backend selection

### 3. Strategy Pattern
- Backend interface with multiple implementations
- Runtime selection based on configuration
- Encapsulated algorithms for different access methods

### 4. Factory Pattern (Implicit)
- Backend selection in `get_backend()`
- Creates appropriate backend based on context

## Auto-Enable Configuration

**File**: `jupyter-config/jupyter_server_config.d/jupyter_mcp_server.json`
```json
{
  "ServerApp": {
    "jpserver_extensions": {
      "jupyter_mcp_server": true
    }
  }
}
```

**Build Configuration** (`pyproject.toml`):
```toml
[tool.hatch.build.targets.wheel.shared-data]
"jupyter-config/jupyter_server_config.d" = "etc/jupyter/jupyter_server_config.d"
```

**Result**: Extension automatically enabled when package is installed.

## Extension Discovery

**Function**: `_jupyter_server_extension_points()` in `jupyter_mcp_server/__init__.py`
```python
def _jupyter_server_extension_points():
    return [{
        "module": "jupyter_mcp_server.jupyter_to_mcp.extension",
        "app": JupyterMCPServerExtensionApp
    }]
```

## Dependencies

**Added for Extension Support**:
- `jupyter_server>=1.6,<3`: Core Jupyter Server
- `tornado>=6.1`: Web framework (already transitively included)
- `traitlets>=5.0`: Configuration system

**Existing Dependencies** (unchanged):
- `jupyter-kernel-client>=0.7.3`
- `jupyter-nbmodel-client>=0.13.5`
- `jupyter-server-api`
- `mcp[cli]>=1.10.1`
- `pydantic`

## Implementation Status

### ✅ Completed (Phase 1 - Foundation)
- [x] Package structure (`jupyter_to_mcp/`)
- [x] ServerContext singleton
- [x] Backend interface (base.py)
- [x] LocalBackend implementation
- [x] RemoteBackend structure
- [x] Protocol messages (Pydantic models)
- [x] JupyterMCPServerExtensionApp
- [x] MCP protocol handlers
- [x] Extension discovery and auto-enable
- [x] Config support for "local" values
- [x] Dependencies updated
- [x] Documentation

### ⏳ Pending (Phase 2 - Integration)
- [ ] BaseToolAdapter implementation
- [ ] Tool-specific adapters
- [ ] Refactor server.py to use adapters
- [ ] Complete RemoteBackend (extract from server.py)
- [ ] Update NotebookManager for backend awareness
- [ ] Integration tests for both modes
- [ ] MCP protocol compliance testing
- [ ] Performance benchmarks

## Testing Strategy

### Unit Tests
- Test ServerContext singleton behavior
- Test backend implementations independently
- Test handler routing logic
- Test Pydantic model validation

### Integration Tests
- **MCP_SERVER Mode**: Regression test suite (existing tests)
- **JUPYTER_SERVER Mode (Local)**: Test with document_url=local, runtime_url=local
- **JUPYTER_SERVER Mode (Remote)**: Test with remote URLs

### Manual Testing
```bash
# Test standalone mode
make start
curl http://localhost:4040/api/healthz

# Test extension mode
make start-as-jupyter-server
curl http://localhost:4040/mcp/healthz
curl http://localhost:4040/mcp/tools/list
```

## Migration Guide

### For Existing Users (No Changes Required)
- Existing standalone MCP server works unchanged
- All configuration, commands, and behavior identical
- Gradual migration path available

### For New Extension Users
1. Install package: `pip install jupyter-mcp-server`
2. Extension auto-enabled (or enable manually)
3. Configure document_url/runtime_url
4. Start Jupyter Server
5. MCP clients connect to `/mcp/` endpoints

## Security Considerations

**Current Implementation** (as specified):
- Anonymous access (no authentication beyond Jupyter's)
- Single-user mode only
- No state management across requests
- No resource limits
- Uses Jupyter Server's logging

**Future Enhancements** (out of scope for initial implementation):
- MCP-specific authentication
- Multi-user support with isolation
- Session state management
- Rate limiting and resource quotas
- Dedicated MCP logging

## Performance Expectations

**Local Backend Advantages**:
- No network latency
- No HTTP/WebSocket overhead
- Direct memory access to notebook data
- Efficient kernel communication

**Expected Improvements** (Local vs Remote):
- List notebooks: 10-50x faster
- Read cells: 5-20x faster
- Execute cells: Similar (kernel-bound)
- File operations: 10-100x faster

## Future Roadmap

1. **Phase 2**: Complete adapter pattern implementation
2. **Phase 3**: Enhanced tool routing and protocol compliance
3. **Phase 4**: Performance optimization and caching
4. **Phase 5**: Multi-user support and authentication
5. **Phase 6**: State management and session persistence
6. **Phase 7**: Resource limits and monitoring

## References

- [Jupyter Server Extension Guide](https://jupyter-server.readthedocs.io/en/latest/developers/extensions.html)
- [MCP Specification (2025-03-26)](https://modelcontextprotocol.io/specification/2025-03-26)
- [Adapter Design Pattern](https://refactoring.guru/design-patterns/adapter)
- [Strategy Design Pattern](https://refactoring.guru/design-patterns/strategy)

---

**Document Version**: 1.0  
**Last Updated**: January 2025  
**Status**: Architecture Implemented, Integration Pending
