<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Architecture Diagram

## Tool Execution Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Claude Desktop / MCP Client                   │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   │ MCP Protocol (JSON-RPC)
                                   │
                ┌──────────────────▼──────────────────┐
                │                                     │
                │         FastMCP Server              │
                │    (server.py @mcp.tool())          │
                │                                     │
                └──────────────────┬──────────────────┘
                                   │
                                   │ Tool name + parameters
                                   │
                ┌──────────────────▼──────────────────┐
                │                                     │
                │        Tool Registry                │
                │   (registry.py)                     │
                │                                     │
                │  - Determines ServerMode            │
                │  - Gets appropriate clients/        │
                │    managers                         │
                │                                     │
                └──────────────────┬──────────────────┘
                                   │
                                   │ tool.execute(mode, ...)
                                   │
        ┌──────────────────────────┴──────────────────────────┐
        │                                                      │
        │              BaseTool.execute()                      │
        │                                                      │
        └──────────────────────────────────────────────────────┘
                         │                 │
                         │                 │
           mode ==       │                 │       mode ==
        MCP_SERVER       │                 │    JUPYTER_SERVER
                         │                 │
                         ▼                 ▼
        ┌────────────────────────┐  ┌────────────────────────┐
        │                        │  │                        │
        │  _operation_http()     │  │  _operation_local()    │
        │                        │  │                        │
        │  Uses:                 │  │  Uses:                 │
        │  - JupyterServerClient │  │  - contents_manager    │
        │  - KernelClient        │  │  - kernel_manager      │
        │                        │  │  - kernel_spec_manager │
        │  (HTTP requests)       │  │  (Direct API calls)    │
        │                        │  │                        │
        └──────────┬─────────────┘  └──────────┬─────────────┘
                   │                           │
                   │                           │
                   ▼                           ▼
        ┌────────────────────────┐  ┌────────────────────────┐
        │                        │  │                        │
        │   Jupyter Server       │  │   Jupyter Server       │
        │   (Remote HTTP API)    │  │   (Local Python API)   │
        │                        │  │                        │
        │   http://localhost:8888│  │   Direct function      │
        │   /api/contents/...    │  │   calls (no HTTP)      │
        │   /api/kernels/...     │  │                        │
        │                        │  │                        │
        └────────────────────────┘  └────────────────────────┘
```

## Mode Detection Flow

```
                    ┌──────────────────────┐
                    │  _get_server_mode()  │
                    └──────────┬───────────┘
                               │
                               │ Check context
                               │
                ┌──────────────▼──────────────┐
                │                             │
                │  Try import ServerContext   │
                │                             │
                └──────────────┬──────────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                │ ImportError?                │
                │                             │
                └──────────────┬──────────────┘
                               │
                      ┌────────┴────────┐
                      │                 │
                     Yes               No
                      │                 │
                      │                 ▼
                      │      ┌────────────────────┐
                      │      │ Check context_type │
                      │      └──────────┬─────────┘
                      │                 │
                      │      ┌──────────┴──────────┐
                      │      │                     │
                      │      │ is_local_document() │
                      │      │ get_contents_mgr()  │
                      │      │                     │
                      │      └──────────┬──────────┘
                      │                 │
                      │        ┌────────┴────────┐
                      │        │                 │
                      │       Yes               No
                      │        │                 │
                      ▼        ▼                 │
          ┌──────────────────────────┐          │
          │                          │          │
          │    ServerMode.           │◄─────────┘
          │    MCP_SERVER            │
          │                          │
          └──────────────────────────┘
                      │
                      │
                      ▼
          ┌──────────────────────────┐
          │                          │
          │    ServerMode.           │
          │    JUPYTER_SERVER        │
          │                          │
          └──────────────────────────┘
```

## Tool Registry Client/Manager Selection

```
┌────────────────────────────────────────────────────────────────┐
│                    ToolRegistry.execute_tool()                  │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           │ Check mode
                           │
          ┌────────────────┴────────────────┐
          │                                 │
          │ mode == MCP_SERVER              │ mode == JUPYTER_SERVER
          │                                 │
          ▼                                 ▼
┌─────────────────────────┐      ┌─────────────────────────┐
│                         │      │                         │
│  Create HTTP clients:   │      │  Get local managers:    │
│                         │      │                         │
│  config = get_config()  │      │  context =              │
│                         │      │    get_server_context() │
│  server_client =        │      │                         │
│    JupyterServerClient( │      │  contents_manager =     │
│      base_url=runtime_  │      │    context.get_contents │
│      url,               │      │    _manager()           │
│      token=runtime_token│      │                         │
│    )                    │      │  kernel_manager =       │
│                         │      │    context.get_kernel_  │
│  kernel_client =        │      │    manager()            │
│    KernelClient(        │      │                         │
│      server_url=runtime │      │  kernel_spec_manager =  │
│      _url,              │      │    context.get_kernel_  │
│      token=runtime_token│      │    spec_manager()       │
│      kernel_id=runtime_ │      │                         │
│      id                 │      │                         │
│    )                    │      │                         │
│                         │      │                         │
└──────────┬──────────────┘      └──────────┬──────────────┘
           │                                │
           │                                │
           └────────────┬───────────────────┘
                        │
                        │ Pass to tool.execute()
                        │
                        ▼
           ┌────────────────────────┐
           │                        │
           │   tool.execute(        │
           │     mode=mode,         │
           │     server_client=..., │
           │     kernel_client=..., │
           │     contents_mgr=...,  │
           │     kernel_mgr=...,    │
           │     ...                │
           │   )                    │
           │                        │
           └────────────────────────┘
```

## Class Hierarchy

```
┌──────────────────────┐
│                      │
│     BaseTool         │
│     (abstract)       │
│                      │
│  + name: str         │
│  + description: str  │
│  + execute(...)      │
│                      │
└──────────┬───────────┘
           │
           │ Inherits
           │
    ┌──────┴──────┬────────────┬─────────────┬──────────────┐
    │             │            │             │              │
    ▼             ▼            ▼             ▼              ▼
┌────────┐  ┌────────────┐ ┌──────────┐ ┌──────────┐  ┌────────┐
│ List   │  │  Connect   │ │Disconnect│ │  Switch  │  │ Read   │
│Notebook│  │  Notebook  │ │ Notebook │ │ Notebook │  │ Cells  │
│Tool    │  │  Tool      │ │  Tool    │ │  Tool    │  │ Tool   │
└────────┘  └────────────┘ └──────────┘ └──────────┘  └────────┘
    │             │            │             │              │
    │             │            │             │              │
    │  Implements │  Implements│  Implements │   Implements │
    │  execute()  │  execute() │  execute()  │   execute()  │
    │             │            │             │              │
    └─────────────┴────────────┴─────────────┴──────────────┘
```

## File Organization

```
jupyter_mcp_server/
│
├── server.py
│   ├── FastMCP instance (mcp)
│   ├── NotebookManager instance (notebook_manager)
│   ├── _initialize_tools()
│   ├── _get_server_mode()
│   └── @mcp.tool() wrappers
│       ├── list_notebook()
│       ├── use_notebook()
│       └── ... (other tools)
│
├── tools/
│   ├── __init__.py
│   │   └── Exports: BaseTool, ServerMode, ToolRegistry, Tool classes
│   │
│   ├── base.py
│   │   ├── ServerMode (enum)
│   │   └── BaseTool (abstract class)
│   │
│   ├── registry.py
│   │   ├── ToolRegistry
│   │   ├── get_tool_registry()
│   │   └── register_tool()
│   │
│   ├── list_notebook.py
│   │   └── ListNotebookTool
│   │       ├── _list_notebooks_http()
│   │       ├── _list_notebooks_local()
│   │       └── execute()
│   │
│   ├── use_notebook.py
│   │   └── ConnectNotebookTool
│   │       ├── _check_path_http()
│   │       ├── _check_path_local()
│   │       └── execute()
│   │
│   ├── disconnect_notebook.py
│   │   └── DisconnectNotebookTool
│   │       └── execute()
│   │
│   └── ... (other tool files)
│
└── jupyter_extension/
    ├── context.py
    │   └── ServerContext
    │       ├── get_contents_manager()
    │       ├── get_kernel_manager()
    │       └── get_kernel_spec_manager()
    │
    ├── extension.py
    │   └── JupyterMCPServerExtensionApp
    │       └── initialize_settings()
    │           └── Updates ServerContext
    │
    └── handlers.py
        └── MCPSSEHandler
            └── Handles MCP protocol
```

## Request Flow Example

**Example: list_notebook() in JUPYTER_SERVER mode**

```
1. Claude Desktop sends MCP request
   ↓
2. MCPSSEHandler receives request
   ↓
3. FastMCP routes to @mcp.tool() wrapper
   ↓
4. Wrapper calls _get_server_mode()
   → Returns ServerMode.JUPYTER_SERVER
   ↓
5. Wrapper calls registry.execute_tool("list_notebook", mode)
   ↓
6. Registry checks mode == JUPYTER_SERVER
   → Gets contents_manager from ServerContext
   ↓
7. Registry calls ListNotebookTool.execute(
     mode=JUPYTER_SERVER,
     contents_manager=contents_manager,
     notebook_manager=notebook_manager
   )
   ↓
8. ListNotebookTool.execute() checks mode
   → Calls self._list_notebooks_local(contents_manager)
   ↓
9. _list_notebooks_local() calls:
   contents_manager.get(path, content=True, type='directory')
   (Direct API call, no HTTP)
   ↓
10. Returns list of notebooks
    ↓
11. FastMCP formats response
    ↓
12. MCPSSEHandler sends JSON-RPC response
    ↓
13. Claude Desktop receives result
```

**Same flow in MCP_SERVER mode:**
- Step 6: Registry creates JupyterServerClient
- Step 8: Calls self._list_notebooks_http(server_client)
- Step 9: Makes HTTP request to http://localhost:8888/api/contents/
