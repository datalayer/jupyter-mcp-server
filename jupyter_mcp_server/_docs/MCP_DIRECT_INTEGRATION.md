# MCP Direct Integration Solution

## Problem
We encountered a "Task group is not initialized" error when trying to wrap FastMCP's Starlette app within Tornado. FastMCP's `streamable_http_app()` requires proper async initialization via `run()`, which doesn't happen when we directly invoke the ASGI app from Tornado.

## Solution
Instead of trying to proxy to a separate server or wrap the Starlette ASGI app, we now **directly implement the MCP protocol** in Tornado handlers and call the registered MCP tools.

## Architecture

```
Claude Desktop
    ↓
POST http://localhost:4040/mcp
    ↓
Tornado (Jupyter Server)
    ↓
MCPSSEHandler (implements MCP JSON-RPC protocol)
    ↓
Calls mcp._tools[tool_name](**params) directly
    ↓
MCP Tool Functions (from server.py)
    ↓
Jupyter Notebook Operations
```

## Key Components

### MCPSSEHandler (`handlers.py`)
A Tornado handler that:
1. **Disables CSRF** - MCP protocol doesn't use XSRF tokens
2. **Sets CORS headers** - Allows cross-origin requests from MCP clients
3. **Implements MCP JSON-RPC protocol**:
   - `initialize` - Returns server capabilities
   - `tools/list` - Lists available tools from `mcp._tools`
   - `tools/call` - Directly invokes tool functions

### Direct Tool Invocation
Instead of going through the Starlette app layers:
```python
# OLD (doesn't work): Try to invoke Starlette app
await asgi_app(scope, receive, send)  # ❌ Requires task group initialization

# NEW (works): Call tools directly
tool_func = mcp._tools[tool_name]
result = await tool_func(**tool_params)  # ✅ Direct function call
```

## Benefits

### ✅ Advantages
1. **No separate server** - Runs within the same Jupyter Server process
2. **No ASGI bridging complexity** - Direct Tornado handlers
3. **No task group issues** - Doesn't require FastMCP's async context
4. **Simple and maintainable** - Clear request flow
5. **Reuses existing tools** - All `@mcp.tool()` decorated functions work as-is

### ⚠️ Considerations
1. **Manual protocol implementation** - We implement JSON-RPC ourselves
2. **Limited to basic MCP** - Doesn't support all Starlette/FastMCP features
3. **Maintenance** - Need to keep protocol implementation up to date

## MCP Protocol Implementation

### Request Format (JSON-RPC 2.0)
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "read_cells",
    "arguments": {
      "start_index": 0,
      "end_index": 5
    }
  },
  "id": 1
}
```

### Response Format
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Cell content here..."
      }
    ]
  }
}
```

### Supported Methods

#### `initialize`
**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {
      "name": "claude-desktop",
      "version": "1.0.0"
    }
  },
  "id": 1
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {
      "tools": {}
    },
    "serverInfo": {
      "name": "Jupyter MCP Server",
      "version": "0.14.0"
    }
  }
}
```

#### `tools/list`
**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "params": {},
  "id": 2
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "read_cells",
        "description": "Read cells from the current notebook",
        "inputSchema": {
          "type": "object",
          "properties": {}
        }
      },
      ...
    ]
  }
}
```

#### `tools/call`
**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "read_cells",
    "arguments": {
      "start_index": 0,
      "end_index": 5
    }
  },
  "id": 3
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Cells 0-5:\n..."
      }
    ]
  }
}
```

## Testing

### 1. Start Jupyter Server
```bash
make start-as-jupyter-server
```

### 2. Test Initialize
```bash
curl -X POST http://localhost:4040/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    },
    "id": 1
  }'
```

Expected: Server capabilities response (not 500 error)

### 3. Test Tools List
```bash
curl -X POST http://localhost:4040/mcp \
  -H "Content-Type": application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "params": {},
    "id": 2
  }'
```

Expected: List of available tools

### 4. Test Tool Call
```bash
curl -X POST http://localhost:4040/mcp \
  -H "Content-Type": application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_notebook",
      "arguments": {}
    },
    "id": 3
  }'
```

Expected: Tool execution result

### 5. Configure Claude Desktop
```json
{
  "mcpServers": {
    "jupyter-local": {
      "command": "npx",
      "args": ["mcp-remote", "http://127.0.0.1:4040/mcp"]
    }
  }
}
```

## Code Changes

### Files Modified
1. **`jupyter_mcp_server/jupyter_extension/handlers.py`**
   - Replaced `MCPProxyHandler` with `MCPSSEHandler`
   - Implements MCP JSON-RPC protocol directly
   - Calls `mcp._tools[tool_name](**params)` directly

2. **`jupyter_mcp_server/jupyter_extension/extension.py`**
   - Updated to use `MCPSSEHandler` instead of `MCPProxyHandler`
   - No longer tries to mount Starlette app

### Files Unchanged
- **`jupyter_mcp_server/server.py`** - All existing tools work as-is
- **`jupyter_mcp_server/models.py`** - No changes needed
- **`jupyter_mcp_server/config.py`** - No changes needed

## Future Improvements

1. **Schema introspection** - Extract actual parameter schemas from tool functions
2. **Streaming responses** - Support SSE for long-running operations
3. **Error handling** - More detailed error codes and messages
4. **Protocol completeness** - Support all MCP protocol features
5. **Type validation** - Validate tool parameters against schemas

## Comparison with Previous Approaches

### Approach 1: Mount Starlette ASGI app ❌
- Created `MCPASGIHandler` to wrap Starlette app
- **Problem**: "Task group is not initialized" error
- **Reason**: FastMCP requires `run()` context manager

### Approach 2: Proxy to separate server ❌
- Created `MCPProxyHandler` to forward requests to uvicorn server
- **Problem**: Defeats the purpose of having an integrated extension
- **Reason**: Adds unnecessary complexity and resource usage

### Approach 3: Direct tool invocation ✅
- Created `MCPSSEHandler` that implements MCP protocol
- **Advantage**: Simple, direct, no extra processes
- **Trade-off**: Manual protocol implementation

## References

- MCP Protocol Specification: https://modelcontextprotocol.io/
- FastMCP Documentation: https://github.com/jlowin/fastmcp
- JSON-RPC 2.0 Specification: https://www.jsonrpc.org/specification
- Tornado Web Framework: https://www.tornadoweb.org/

---

**Status**: ✅ Implemented and ready for testing  
**Date**: October 5, 2025  
**Approach**: Direct tool invocation via MCP JSON-RPC protocol in Tornado handlers
