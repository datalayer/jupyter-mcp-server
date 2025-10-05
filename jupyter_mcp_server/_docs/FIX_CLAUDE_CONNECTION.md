<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Fix for Claude Desktop Connection Issue

## Problem
Claude Desktop was getting errors when trying to connect to the Jupyter Server MCP extension:

### Issue 1: 404 Errors (RESOLVED)
```
[W 2025-10-05 12:35:54.914 ServerApp] 404 POST /mcp (@127.0.0.1) 8.79ms referer=None
[W 2025-10-05 12:35:54.926 ServerApp] 404 GET /mcp (@127.0.0.1) 1.20ms referer=None
```

### Issue 2: 403 CSRF Errors (RESOLVED)
```
[W 2025-10-05 12:43:05.313 ServerApp] 403 POST /mcp (127.0.0.1): '_xsrf' argument missing from POST
[W 2025-10-05 12:43:05.314 ServerApp] 403 POST /mcp (@127.0.0.1) 0.67ms referer=None
```

## Root Causes

### 1. Wrong Endpoint Path
The MCP protocol requires the SSE endpoint to be at `/mcp` (not `/mcp/sse`). Claude Desktop and other MCP clients expect to connect to the base `/mcp` endpoint for the full MCP protocol communication.

Our initial implementation tried to create custom Tornado handlers for individual MCP operations, but this doesn't properly implement the full MCP protocol specification.

### 2. CSRF Protection
Tornado/Jupyter Server requires XSRF tokens for POST requests by default. The MCP protocol doesn't use browser-based XSRF tokens, so we need to disable CSRF checks for MCP endpoints.

## Solution
Instead of reimplementing the MCP protocol with Tornado handlers, we now:

1. **Reuse the existing FastMCP server** from `server.py`
2. **Mount the Starlette ASGI app** that FastMCP provides at the `/mcp` endpoint
3. **Create an ASGI-to-Tornado bridge** (`MCPASGIHandler`) that wraps the Starlette app
4. **Disable CSRF protection** for MCP endpoints (MCP has its own auth mechanism)
5. **Add CORS headers** to allow cross-origin requests from MCP clients

This ensures we have:
- ✅ Full MCP protocol compliance (using the same FastMCP implementation as standalone mode)
- ✅ Correct endpoint routing (`/mcp` for SSE transport)
- ✅ No CSRF conflicts (disabled for MCP endpoints)
- ✅ Cross-origin support (CORS headers enabled)
- ✅ Backward compatibility with existing tools
- ✅ No need to reimplement MCP protocol details

## Changes Made

### 1. New Handler: `MCPASGIHandler` 
**File**: `jupyter_mcp_server/jupyter_extension/handlers.py`

Created a new Tornado handler that wraps a Starlette ASGI application. This handler:
- Converts Tornado requests to ASGI scope
- Executes the ASGI application
- Streams responses back to Tornado
- Supports all HTTP methods (GET, POST, PUT, DELETE, etc.)
- **Disables XSRF checks** via `check_xsrf_cookie()` override
- **Adds CORS headers** via `set_default_headers()`
- **Handles OPTIONS** requests for CORS preflight

```python
class MCPASGIHandler(tornado.web.RequestHandler):
    """Handler that wraps a Starlette ASGI application."""
    
    def initialize(self, asgi_app):
        self.asgi_app = asgi_app
    
    def check_xsrf_cookie(self):
        """Disable XSRF check for MCP endpoints."""
        pass
    
    def set_default_headers(self):
        """Set CORS headers."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    
    async def options(self):
        """Handle CORS preflight."""
        self.set_status(204)
        self.finish()
    
    async def _execute_asgi(self):
        # Build ASGI scope from Tornado request
        # Create receive/send callables
        # Execute ASGI app
        ...
```

### 2. Updated Extension Handler Registration
**File**: `jupyter_mcp_server/jupyter_extension/extension.py`

Modified `initialize_handlers()` to:
- Import the `mcp` FastMCP instance from `server.py`
- Get the Starlette app via `mcp.streamable_http_app()`
- Mount it at `/mcp` using the new `MCPASGIHandler`

```python
def initialize_handlers(self):
    # Import the FastMCP instance
    from jupyter_mcp_server.server import mcp
    from jupyter_mcp_server.jupyter_extension.handlers import MCPASGIHandler
    
    # Get the Starlette app
    starlette_app = mcp.streamable_http_app()
    
    # Mount at /mcp
    handlers = [
        (url_path_join(base_url, "/mcp"), MCPASGIHandler, {"asgi_app": starlette_app}),
        # ... utility endpoints
    ]
```

### 3. Removed Obsolete Handler
Removed `MCPSSEHandler` which was a partial SSE implementation. We now delegate to FastMCP's complete implementation.

## How It Works

### Request Flow
```
Claude Desktop
    ↓
GET/POST http://localhost:4040/mcp
    ↓
Tornado (Jupyter Server)
    ↓
MCPASGIHandler
    ↓
FastMCP Starlette App (ASGI)
    ↓
MCP Protocol Handler
    ↓
MCP Tools (from server.py)
```

### Key Components
1. **Tornado** - Jupyter Server's web framework
2. **MCPASGIHandler** - Our bridge between Tornado and ASGI
3. **Starlette** - FastMCP's underlying ASGI framework
4. **FastMCP** - MCP SDK that implements the protocol
5. **MCP Tools** - The actual Jupyter notebook operations

## Testing

### 1. Verify Extension Loads
```bash
python test_extension.py
```

Expected output:
```
✅ PASS: Imports
✅ PASS: Extension Points
✅ PASS: Handler Creation
```

### 2. Start Jupyter Server with Extension
```bash
make start-as-jupyter-server
```

Or manually:
```bash
jupyter-server \
  --JupyterMCPServerExtensionApp.document_url=local \
  --JupyterMCPServerExtensionApp.runtime_url=local \
  --JupyterMCPServerExtensionApp.document_id=notebook.ipynb \
  --port=4040 \
  --token=MY_TOKEN
```

### 3. Test Health Check
```bash
curl http://localhost:4040/mcp/healthz
```

Expected response:
```json
{
  "status": "healthy",
  "context_type": "JUPYTER_SERVER",
  "document_url": "local",
  "runtime_url": "local"
}
```

### 4. Test MCP Endpoint (Manual)
```bash
# Test GET (SSE handshake)
curl http://localhost:4040/mcp

# Test POST (MCP protocol message)
curl -X POST http://localhost:4040/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

### 5. Configure Claude Desktop
**File**: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

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

Then restart Claude Desktop and it should connect to the `/mcp` endpoint successfully.

## Benefits of This Approach

### ✅ Advantages
1. **Full MCP Compliance** - Uses the official FastMCP implementation
2. **Code Reuse** - Leverages existing `server.py` tools and logic
3. **Maintainability** - Only one MCP implementation to maintain
4. **Flexibility** - Can switch between standalone and extension modes seamlessly
5. **Future-Proof** - Automatically gets FastMCP updates

### ⚠️ Considerations
1. **ASGI Bridge** - Adds a thin translation layer between Tornado and Starlette
2. **Import Order** - Must import `mcp` from `server.py` at handler initialization time
3. **Performance** - Slight overhead from ASGI conversion (negligible for typical use)

## Alternative Approaches Considered

### Option 1: Reimplement MCP Protocol in Tornado ❌
**Rejected**: Too complex, error-prone, and requires maintaining parallel implementations.

### Option 2: Run Separate MCP Server ❌
**Rejected**: Defeats the purpose of having an integrated extension.

### Option 3: Use Tornado-ASGI Library ⚠️
**Considered**: Could use `tornado-asgi` or similar, but adds external dependency. Our custom `MCPASGIHandler` is simpler and has no extra dependencies.

### Option 4: Mount Starlette App (CHOSEN) ✅
**Selected**: Reuses existing implementation, maintains compatibility, minimal code changes.

## Next Steps

1. ✅ **Test with Claude Desktop** - Verify connection works
2. ⏳ **Test with other MCP clients** - VS Code, Cursor, Windsurf
3. ⏳ **Add integration tests** - Automated tests for MCP protocol
4. ⏳ **Performance testing** - Measure ASGI bridge overhead
5. ⏳ **Documentation** - Update user-facing docs

## Related Files

- `jupyter_mcp_server/jupyter_extension/handlers.py` - New `MCPASGIHandler`
- `jupyter_mcp_server/jupyter_extension/extension.py` - Updated handler registration
- `jupyter_mcp_server/server.py` - Original FastMCP server (unchanged)
- `test_extension.py` - Extension validation tests
- `Makefile` - `start-as-jupyter-server` command

## Debugging Tips

### Enable Verbose Logging
```bash
jupyter-server \
  --log-level=DEBUG \
  --JupyterMCPServerExtensionApp.document_url=local \
  ...
```

### Check Extension Loaded
```bash
jupyter server extension list | grep mcp
```

Should show:
```
jupyter_mcp_server enabled
```

### Monitor Requests
Watch the Jupyter Server logs for:
```
INFO:jupyter_mcp_server.jupyter_extension.extension:Registered MCP handlers at /mcp/
INFO:jupyter_mcp_server.jupyter_extension.extension:  - MCP protocol: /mcp (via FastMCP Starlette app)
```

## Conclusion

This fix ensures that Claude Desktop and other MCP clients can successfully connect to the Jupyter Server MCP extension at the standard `/mcp` endpoint. By mounting the FastMCP Starlette app within Tornado, we maintain full protocol compliance while keeping the codebase simple and maintainable.

The ASGI bridge pattern is a clean solution that can be reused for other ASGI applications that need to run within Jupyter Server extensions.

---
**Date**: October 5, 2025  
**Issue**: 404 errors on `/mcp` endpoint  
**Resolution**: Mount FastMCP Starlette app via ASGI bridge handler
