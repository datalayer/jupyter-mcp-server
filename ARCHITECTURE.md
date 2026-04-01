<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
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
│                       MCP Client                                │
│            (Claude Desktop, VS Code, Cursor, etc.)              │
└────────────┬────────────────────────────────────┬───────────────┘
             │                                    │
             │ stdio/SSE                          │ HTTP/SSE
             │                                    │
    ┌────────▼────────────┐          ┌───────────▼──────────────┐
    │   MCP_SERVER Mode   │          │  JUPYTER_SERVER Mode     │
    │   (Standalone)      │          │  (Extension)             │
    │                     │          │                          │
    │   CLI Layer         │          │    Extension Handlers    │
    │  (CLI.py)           │          │  (handlers.py)           │
    └──────────┬──────────┘          └──────────┬───────────────┘
               │                                │
               │ Configuration                  │ Configuration
               │                                │
    ┌──────────▼──────────┐          ┌──────────▼──────────────┐
    │   Server Layer      │          │   Extension Context     │
    │  (server.py)        │          │  (context.py)           │
    │                     │          │                         │
    │  - FastMCP Server   │          │  - ServerApp Access     │
    │  - Tool Wrappers    │          │  - Manager Access       │
    │  - Error Handling   │          │  - Backend Selection    │
    └──────────┬──────────┘          └──────────┬──────────────┘
               │                                │
               │ Tool Delegation                │ Tool Delegation
               │                                │
        ┌──────▼────────────────────────────────▼──────┐
        │          Tool Implementation Layer           │
        │         (jupyter_mcp_server/tools/)          │
        │                                              │
        │  14 Tools in 3 Categories:                   │
        │  • Server Management (2)                     │
        │  • Multi-Notebook Management (5)             │
        │  • Cell Operations (7)                       │
        │                                              │
        │  Each tool implements:                       │
        │  - Dual-mode execution logic                 │
        │  - Backend abstraction                       │
        │  - Error handling and recovery               │
        └──────────┬───────────────────────┬───────────┘
                   │                       │
                   │ Mode Selection        │ Backend Selection
                   │                       │
          ┌────────▼────────┐     ┌────────▼────────┐
          │ Remote Backend  │     │  Local Backend  │
          │                 │     │                 │
          │ - HTTP Clients  │     │ - Direct API    │
          │ - WebSocket     │     │ - Zero Overhead │
          │ - Client Libs   │     │ - YDoc Support  │
          └────────┬────────┘     └────────┬────────┘
                   │                       │
                   │ HTTP/WS               │ Direct Python API
                   │                       │
            ┌──────▼──────────┐    ┌───────▼────────┐
            │ Remote Jupyter  │    │ Local Jupyter  │
            │ Server          │    │ Server         │
            └─────────────────┘    └────────────────┘
```

## Core Components

### 1. CLI Layer (`CLI.py`)

**Command-Line Interface** - Primary entry point for users and MCP clients:

**Key Features**:
- **Configuration Management**: Handles all startup configuration via command-line options and environment variables
- **Transport Selection**: Supports both `stdio` (for direct MCP client integration) and `streamable-http` (for HTTP-based clients)
- **Auto-Enrollment**: Automatically connects to specified notebooks on startup
- **Provider Support**: Supports both `jupyter` and `datalayer` providers
- **URL Resolution**: Intelligent URL and token resolution with fallback mechanisms

**Integration**:
- Calls `server.py` functions to initialize the MCP server
- Passes configuration to `ServerContext` for mode detection
- Handles kernel startup and notebook enrollment lifecycle

### 2. Backend Layer (`jupyter_mcp_server/jupyter_extension/backends/`)

**Backend Abstraction** - Unified interface for notebook and kernel operations:

**LocalBackend** - Complete implementation using local Jupyter Server APIs:
- Uses `serverapp.contents_manager` for file operations
- Uses `serverapp.kernel_manager` for kernel operations
- Direct Python API calls with minimal overhead
- Supports both file-based and YDoc collaborative editing

**RemoteBackend** - Placeholder implementation for HTTP/WebSocket access:
- Designed for `jupyter_server_client`, `jupyter_kernel_client`, `jupyter_nbmodel_client`
- Maintains 100% backward compatibility with existing MCP_SERVER mode
- Currently marked as "Not Implemented" - to be refactored from server.py

### 3. Server Context Layer

**Multiple Context Managers**:

**MCP Server Context** (`server_context.py::ServerContext`):
- Singleton managing server mode for standalone MCP_SERVER mode
- Provides HTTP clients for remote Jupyter server access
- Mode detection based on configuration

**Extension Context** (`jupyter_extension/context.py::ServerContext`):
- Singleton managing server mode for JUPYTER_SERVER extension mode
- Provides direct access to serverapp managers (contents_manager, kernel_manager)
- Handles configuration from Jupyter extension traits

**Mode Detection**:
- **JUPYTER_SERVER**: When running as extension, serverapp available
- **MCP_SERVER**: When running standalone, connects via HTTP

### 4. FastMCP Server Layer (`server.py`)

**FastMCP Integration** - Core MCP protocol implementation:

```python
# Global MCP server instance with CORS support
mcp = FastMCPWithCORS(name="Jupyter MCP Server", json_response=False, stateless_http=True)
notebook_manager = NotebookManager()
server_context = ServerContext.get_instance()

# Tool registration and execution
@mcp.tool()
async def list_files(path: str = "", max_depth: int = 1, ...) -> str:
    """List files and directories in Jupyter server filesystem"""
    return await safe_notebook_operation(
        lambda: ListFilesTool().execute(
            mode=server_context.mode,
            server_client=server_context.server_client,
            contents_manager=server_context.contents_manager,
            path=path,
            max_depth=max_depth,
            ...
        )
    )
```

**Key Responsibilities**:
- **Tool Registration**: All 14 MCP tools are registered as FastMCP decorators
- **Mode Detection**: Automatically detects and initializes appropriate server mode
- **Error Handling**: Provides `safe_notebook_operation()` wrapper with retry logic
- **Resource Management**: Manages notebook connections and kernel lifecycle
- **Protocol Bridge**: Translates between MCP protocol and internal tool implementations

**Transport Support**:
- **stdio**: Direct communication with MCP clients via standard input/output
- **streamable-http**: HTTP-based communication with SSE (Server-Sent Events) support
- **CORS Middleware**: Enables cross-origin requests for web-based MCP clients

### 5. Tool Implementation Layer (`jupyter_mcp_server/tools/`)

**Built-in Tool Implementations** - Complete set of Jupyter operations:

```python
# Tool Categories and Examples

# Server Management (2 tools)
class ListFilesTool(BaseTool):      # File system exploration
class ListKernelsTool(BaseTool):    # Kernel management

# Multi-Notebook Management (5 tools)
class UseNotebookTool(BaseTool):    # Connect/create notebooks
class ListNotebooksTool(BaseTool):  # List managed notebooks
class RestartNotebookTool(BaseTool): # Restart kernels
class UnuseNotebookTool(BaseTool):  # Disconnect notebooks
class ReadNotebookTool(BaseTool):   # Read notebook content

# Cell Operations (7 tools)
class InsertCellTool(BaseTool):     # Insert new cells
class DeleteCellTool(BaseTool):     # Delete cells
class OverwriteCellSourceTool(BaseTool): # Modify cell content
class ExecuteCellTool(BaseTool):    # Execute cells with streaming
class ReadCellTool(BaseTool):       # Read individual cells
class ExecuteCodeTool(BaseTool):    # Execute arbitrary code
class InsertExecuteCodeCellTool(BaseTool): # Combined insert+execute
```

**Implementation Architecture**:
- **BaseTool Abstract Class**: Defines `execute()` method signature with dual-mode support
- **ServerMode Enum**: Distinguishes between `MCP_SERVER` and `JUPYTER_SERVER` modes
- **Dual-Mode Logic**: Each tool implements both local and remote execution paths
- **Backend Integration**: Tools automatically select appropriate backend based on mode

**Tool Categories**:
1. **Server Management**: File system and kernel introspection
2. **Multi-Notebook Management**: Notebook lifecycle and connection management
3. **Cell Operations**: Fine-grained cell manipulation and execution

**Dynamic Tool Registry** (`get_registered_tools()`):
- Queries FastMCP's `list_tools()` to get all registered tools
- Returns tool metadata (name, description, parameters, inputSchema)
- Used by Jupyter extension to expose tools without hardcoding
- Supports both FastMCP tools and jupyter-mcp-tools integration

### 6. Jupyter Extension Layer (`jupyter_extension/`)

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

### 7. Notebook Manager (`notebook_manager.py`)

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

### 8. Hook System (`hooks.py`, `otel_hook.py`)

**Pre/Post Hook System** - Observability and extensibility layer:

```python
class HookEvent(str, Enum):
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    BEFORE_EXECUTE = "before_execute"
    AFTER_EXECUTE = "after_execute"
    KERNEL_LIFECYCLE = "kernel_lifecycle"
```

**Key Components**:
- **HookRegistry**: Singleton that manages handler registration and event dispatch
- **HookHandler Protocol**: Interface for custom handlers with `propagate_errors` flag
- **`@with_hooks` Decorator**: Applied to all tool functions in `server.py` to fire `BEFORE_TOOL_CALL` / `AFTER_TOOL_CALL` events
- **Context Correlation**: Before/after event pairs share a context dict for handler state

**Built-in OTel Handler** (`otel_hook.py`):
- Emits OpenTelemetry spans for tool calls, code execution, and kernel lifecycle
- Uses `FileSpanExporter` to write spans as JSONL
- Activated via `--otel-file` CLI arg, `JUPYTER_MCP_OTEL_FILE` env var, or Jupyter traitlet
- Non-propagating (`propagate_errors = False`) — never disrupts tool execution

**Integration Points**:
- `server.py`: All tools decorated with `@with_hooks`; kernel lifecycle events fired on use/restart/unuse
- `execute_cell_tool.py`, `execute_code_tool.py`: Fire `BEFORE_EXECUTE` / `AFTER_EXECUTE` around kernel execution
- `utils.py`: Fires execution hooks in shared utility functions

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
- Tools use HTTP clients for remote Jupyter server access
- Notebook connections use `NbModelClient` for WebSocket (Y.js documents)
- Uses RemoteBackend (placeholder implementation)

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

**Backend Selection**:
- **LocalBackend**: Used when `document_url="local"` or `runtime_url="local"`
  - Direct access to `serverapp.contents_manager`, `serverapp.kernel_manager`
  - No network overhead, maximum performance
  - Supports both file-based and YDoc collaborative editing
- **RemoteBackend**: Used when connecting to remote Jupyter servers
  - HTTP/WebSocket access via client libraries
  - Placeholder implementation (to be completed)

**Behavior**:
- Extension auto-enabled (via `jupyter-config/` file)
- ServerContext updated with `mode=ServerMode.JUPYTER_SERVER`
- Tools automatically select LocalBackend for optimal performance
- Cell reading tools parse notebook JSON from file system or YDoc

## Request Flow Examples

### Example 1: List Notebooks (JUPYTER_SERVER Mode with LocalBackend)

```
MCP Client
  → POST /mcp/tools/call {"tool_name": "list_notebooks"}
    → MCPSSEHandler (or MCPToolsCallHandler)
      → FastMCP calls @mcp.tool() wrapper
        → ListNotebooksTool().execute(
            mode=JUPYTER_SERVER,
            notebook_manager=notebook_manager
          )
          → notebook_manager.list_all_notebooks()
            → Returns managed notebooks from memory
          ← TSV-formatted table
        ← Tool result
      ← JSON-RPC response
    ← SSE message
  ← Tool result displayed
```

### Example 2: Read Cell (JUPYTER_SERVER Mode with LocalBackend)

```
MCP Client
  → POST /mcp/tools/call {"tool_name": "read_cell", "arguments": {"cell_index": 0}}
    → MCPSSEHandler (or MCPToolsCallHandler)
      → FastMCP calls @mcp.tool() wrapper
        → ReadCellTool().execute(
            mode=JUPYTER_SERVER,
            contents_manager=serverapp.contents_manager,
            notebook_manager=notebook_manager
          )
          → LocalBackend.get_notebook_content(notebook_path)
            → contents_manager.get(notebook_path, content=True, type='notebook')
              → Direct file system access (no HTTP)
            ← Notebook JSON content
          → Parse cells and format response
          ← Cell information with metadata and source
        ← Tool result
      ← JSON-RPC response
    ← SSE message
  ← Cell content displayed
```

### Example 3: Execute Cell (MCP_SERVER Mode with RemoteBackend)

```
MCP Client
  → POST /mcp/tools/call {"tool_name": "execute_cell", "arguments": {"cell_index": 0}}
    → FastMCP calls @mcp.tool() wrapper
      → ExecuteCellTool().execute(
          mode=MCP_SERVER,
          notebook_manager=notebook_manager
        )
        → notebook_manager.get_current_connection()
          → NbModelClient establishes WebSocket to Y.js document
          → Access collaborative Y.js document
        → Execute code via kernel connection
          → HTTP/WebSocket to remote kernel
          → Real-time execution with progress updates
        ← Execution outputs with rich formatting
      ← Tool result
    ← Response
  ← Outputs displayed
```

## Tool Registration Flow

```
1. CLI startup (CLI.py)
   ↓
2. Configuration parsing and validation
   ↓
3. ServerContext initialization with mode detection
   ↓
4. FastMCP server initialization (server.py)
   ↓
5. Tool instance creation (14 tool implementations)
   ↓
6. @mcp.tool() wrapper registration
   ↓
7. FastMCP internal tool registry
   ↓
8. Dynamic tool discovery via get_registered_tools()
   ↓
9. Extension handlers expose tools via /mcp/tools/list
   ↓
10. MCP clients discover and invoke tools
```

## File Structure

```
jupyter_mcp_server/
├── __init__.py                 # Package initialization
├── __main__.py                 # Module entry point (imports CLI)
├── __version__.py              # Version information (0.17.1)
│
├── CLI.py                      # 🏠 Command-Line Interface (Primary Entry Point)
│   ├── Command parsing and validation
│   ├── Environment variable handling
│   ├── Transport selection (stdio/streamable-http)
│   ├── Provider support (jupyter/datalayer)
│   ├── Auto-enrollment of notebooks
│   └── Server lifecycle management
│
├── server.py                   # 🔧 FastMCP Server Layer
│   ├── MCP protocol implementation
│   ├── Tool registration (14 @mcp.tool decorators)
│   ├── Error handling with safe_notebook_operation()
│   ├── Resource management and cleanup
│   ├── Dynamic tool registry (get_registered_tools())
│   └── Transport support (stdio + streamable-http)
│
├── tools/                      # 🛠️ Built-in Tool Implementations
│   ├── __init__.py            # Exports BaseTool, ServerMode
│   ├── _base.py               # Abstract base class for all tools
│   │
│   # Server Management Tools (2)
│   ├── list_files_tool.py     # File system exploration
│   ├── list_kernels_tool.py   # Kernel introspection
│   │
│   # Multi-Notebook Management Tools (5)
│   ├── use_notebook_tool.py   # Connect/create notebooks
│   ├── list_notebooks_tool.py # List managed notebooks
│   ├── restart_notebook_tool.py # Restart kernels
│   ├── unuse_notebook_tool.py # Disconnect notebooks
│   ├── read_notebook_tool.py  # Read notebook content
│   │
│   # Cell Operation Tools (7)
│   ├── read_cell_tool.py      # Read individual cells
│   ├── insert_cell_tool.py    # Insert new cells
│   ├── delete_cell_tool.py    # Delete cells
│   ├── overwrite_cell_source_tool.py # Modify cell content
│   ├── execute_cell_tool.py   # Execute cells with streaming
│   ├── execute_code_tool.py   # Execute arbitrary code
│   └── insert_execute_code_cell # Combined insert+execute (inline in server.py)
│
├── config.py                   # ⚙️ Configuration Management
│   ├── Singleton config object (JupyterMCPConfig)
│   ├── Environment variable parsing
│   ├── URL and token resolution
│   └── Provider-specific settings
│
├── notebook_manager.py         # 📚 Notebook Lifecycle Management
│   ├── Multi-notebook support
│   ├── Kernel connection management
│   ├── Context managers for resources
│   └── Dual-mode operation (local/remote)
│
├── server_context.py           # 🎯 Server Context (MCP_SERVER mode)
│   ├── Mode detection and initialization
│   ├── HTTP client management
│   └── Configuration state management
│
├── utils.py                    # 🧰 Utility Functions
│   ├── Execution utilities (local/remote)
│   ├── Output processing and formatting
│   ├── Kernel management helpers
│   └── YDoc integration support
│
├── hooks.py                    # 🔍 Hook System
│   ├── HookEvent enum (5 event types)
│   ├── HookHandler protocol
│   ├── HookRegistry singleton
│   └── @with_hooks decorator
│
├── otel_hook.py                # 📡 OpenTelemetry Integration
│   ├── OTelHookHandler (span emission)
│   ├── FileSpanExporter (JSONL output)
│   └── maybe_register_otel() auto-setup
│
├── enroll.py                   # 🔗 Auto-Enrollment System
│   ├── Automatic notebook connection
│   ├── Kernel startup and management
│   └── Configuration-based initialization
│
├── models.py                   # 📋 Data Models
│   ├── Pydantic models for API
│   ├── Cell and Notebook structures
│   └── Configuration validation
│
└── jupyter_extension/          # 🔌 Jupyter Server Extension
    ├── extension.py           # Jupyter extension app
    ├── handlers.py            # HTTP request handlers
    ├── context.py             # Extension context manager
    ├── backends/              # Backend implementations
    │   ├── base.py            # Backend interface
    │   ├── local_backend.py   # Local API (Complete)
    │   └── remote_backend.py  # Remote API (Placeholder)
    └── protocol/              # Protocol implementation
        └── messages.py        # MCP message models
```

## References

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [Jupyter Server Extension Guide](https://jupyter-server.readthedocs.io/en/latest/developers/extensions.html)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Y.js Collaborative Editing](https://github.com/yjs/yjs)

---

**Version**: 0.2.0
**Last Updated**: October 2025
**Status**: Complete implementation with dual-mode architecture and backend abstraction
