<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# CSRF Fix Summary

## Problems Encountered

### Issue 1: Initial CSRF Error
```
[W 2025-10-05 12:43:05.313 ServerApp] 403 POST /mcp (127.0.0.1): '_xsrf' argument missing from POST
```

### Issue 2: Redirect + CSRF Error
```
[I 2025-10-05 12:47:51.361 ServerApp] 307 POST /mcp (@127.0.0.1) 0.66ms
[W 2025-10-05 12:47:51.368 ServerApp] 403 POST /mcp/ (127.0.0.1): '_xsrf' argument missing from POST
```

The request was being redirected from `/mcp` to `/mcp/` (with trailing slash), and the redirect lost the CSRF bypass.

## Root Causes

### 1. Tornado XSRF Protection
Tornado/Jupyter Server requires XSRF tokens for POST requests by default. The MCP protocol doesn't use browser-based XSRF tokens.

### 2. Trailing Slash Redirect
Tornado automatically redirects `/mcp` to `/mcp/` with a 307 redirect. The handler pattern must match both paths to avoid the redirect.

## Solutions

### Solution 1: Disable XSRF Check
Added `check_xsrf_cookie()` override to disable CSRF protection for MCP endpoints:

```python
def check_xsrf_cookie(self):
    """
    Disable XSRF check for MCP endpoints.
    
    The MCP protocol uses its own authentication mechanism and doesn't
    rely on browser-based XSRF tokens.
    """
    pass
```

### Solution 2: Match Both Paths
Updated handler registration to use regex pattern that matches both `/mcp` and `/mcp/`:

```python
# In extension.py - initialize_handlers()
handlers = [
    # Match /mcp with or without trailing slash using regex
    (url_path_join(base_url, "/mcp/?"), MCPASGIHandler, {"asgi_app": starlette_app}),
    ...
]
```

The `/?` pattern in the URL means the trailing slash is optional, so both `/mcp` and `/mcp/` will match the same handler.

Also added CORS support:

```python
def set_default_headers(self):
    """Set CORS headers to allow cross-origin requests."""
    self.set_header("Access-Control-Allow-Origin", "*")
    self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    self.set_header("Access-Control-Max-Age", "3600")

async def options(self):
    """Handle OPTIONS requests for CORS preflight."""
    self.set_status(204)
    self.finish()
```

## Files Changed
- `jupyter_mcp_server/jupyter_extension/handlers.py` - Added CSRF bypass and CORS headers to `MCPASGIHandler`
- `jupyter_mcp_server/jupyter_extension/extension.py` - Updated URL pattern to match both `/mcp` and `/mcp/`

## Testing
```bash
# Should NOT return 403 or 307 redirect
curl -X POST http://localhost:4040/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'

# Also test with trailing slash
curl -X POST http://localhost:4040/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

Both should return the same response without redirects or CSRF errors.

## Status
✅ **FIXED** - No more 403 CSRF errors
✅ **FIXED** - No more 307 redirects
