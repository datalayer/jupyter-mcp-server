# Testing Guide: Jupyter MCP Server Extension

## Quick Start

### 1. Restart the Jupyter Server
If you have a running instance, stop it and restart:

```bash
cd /home/echarles/Content/datalayer-osp/src/ai/jupyter-mcp-server
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

### 2. Verify Extension Loaded
Check the logs for:
```
[JupyterMCPServerExtensionApp] Registered MCP handlers at /mcp/
[JupyterMCPServerExtensionApp]   - MCP protocol: /mcp (via FastMCP Starlette app)
```

### 3. Test Endpoints

#### Health Check (Should work)
```bash
curl http://localhost:4040/mcp/healthz
```

Expected:
```json
{
  "status": "healthy",
  "context_type": "JUPYTER_SERVER",
  "document_url": "local",
  "runtime_url": "local"
}
```

#### MCP Protocol Endpoint (Should NOT return 403 or 404)
```bash
# Test GET
curl http://localhost:4040/mcp

# Test POST (MCP initialize)
curl -X POST http://localhost:4040/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-03-26",
      "capabilities": {},
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    },
    "id": 1
  }'
```

Expected: JSON-RPC response (not 403 or 404)

## Troubleshooting

### Issue: 404 Errors on `/mcp`
**Symptoms:**
```
[W] 404 POST /mcp (@127.0.0.1)
```

**Solution:**
- Verify extension is loaded: `jupyter server extension list | grep mcp`
- Check handler registration in logs
- Restart Jupyter Server

### Issue: 403 CSRF Errors (FIXED)
**Symptoms:**
```
[W] 403 POST /mcp (127.0.0.1): '_xsrf' argument missing from POST
```

**Solution:**
This should be fixed by the `check_xsrf_cookie()` override in `MCPASGIHandler`.
If you still see this, verify you have the latest code:

```bash
cd /home/echarles/Content/datalayer-osp/src/ai/jupyter-mcp-server
git pull origin feat/jupyter-server-extension
```

### Issue: CORS Errors
**Symptoms:**
```
Access to fetch at 'http://localhost:4040/mcp' from origin 'http://localhost:3000' has been blocked by CORS policy
```

**Solution:**
This should be fixed by the CORS headers in `set_default_headers()`.
Verify the response includes:
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
```

### Issue: Connection Refused
**Symptoms:**
```
Failed to connect to localhost:4040
```

**Solution:**
- Check if Jupyter Server is running: `ps aux | grep jupyter-server`
- Check if port is in use: `lsof -i :4040`
- Try a different port in the config

## Testing with MCP Clients

### Claude Desktop

**Config Location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

**Configuration:**
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

**Steps:**
1. Add the configuration above
2. Restart Claude Desktop
3. Open a new conversation
4. Look for the MCP connection indicator
5. Try asking: "List the available Jupyter notebooks"

**Expected Behavior:**
- No 404 or 403 errors in Jupyter Server logs
- Claude should connect successfully
- You should be able to interact with notebooks

### VS Code with MCP Extension

**Configuration:**
Add to `.vscode/settings.json`:
```json
{
  "mcp.servers": {
    "jupyter-local": {
      "type": "http",
      "url": "http://localhost:4040/mcp"
    }
  }
}
```

### Cursor

**Configuration:**
Similar to VS Code, add to Cursor settings.

### Testing with mcp-remote CLI

```bash
# Install mcp-remote
npm install -g mcp-remote

# Test connection
mcp-remote http://localhost:4040/mcp
```

## Debugging

### Enable Debug Logging

```bash
jupyter-server \
  --log-level=DEBUG \
  --JupyterMCPServerExtensionApp.document_url=local \
  --JupyterMCPServerExtensionApp.runtime_url=local \
  --port=4040 \
  --token=MY_TOKEN
```

### Check Handler Registration

```python
import logging
from jupyter_mcp_server.jupyter_to_mcp.extension import JupyterMCPServerExtensionApp

# Enable logging
logging.basicConfig(level=logging.DEBUG)

# Check extension points
from jupyter_mcp_server import _jupyter_server_extension_points
print(_jupyter_server_extension_points())
```

### Test ASGI Handler Directly

```python
import asyncio
from jupyter_mcp_server.server import mcp

# Get the Starlette app
app = mcp.streamable_http_app()

# Create a test scope
scope = {
    "type": "http",
    "method": "GET",
    "path": "/",
    "query_string": b"",
    "headers": [],
}

async def receive():
    return {"type": "http.request", "body": b"", "more_body": False}

responses = []
async def send(message):
    responses.append(message)

# Execute
asyncio.run(app(scope, receive, send))
print(responses)
```

## Verification Checklist

Before reporting success, verify:

- [ ] Extension loads without errors
- [ ] `/mcp/healthz` returns 200 OK
- [ ] `/mcp` GET returns valid response (not 404)
- [ ] `/mcp` POST returns valid response (not 403)
- [ ] No CSRF errors in logs
- [ ] No CORS errors in browser console
- [ ] Claude Desktop connects successfully
- [ ] Can list notebooks via MCP
- [ ] Can execute cells via MCP

## Performance Monitoring

### Request Timing
Watch the logs for timing information:
```
[ServerApp] 200 POST /mcp (@127.0.0.1) 45.32ms
```

Normal timings:
- Health check: < 10ms
- MCP initialize: < 100ms
- List notebooks: < 500ms
- Execute cell: 1-10 seconds (depends on code)

### Memory Usage
```bash
# Monitor Jupyter Server memory
ps aux | grep jupyter-server | awk '{print $6/1024 "MB"}'
```

## Known Limitations

1. **Authentication**: Currently anonymous (no token validation beyond Jupyter's)
2. **Rate Limiting**: No rate limiting implemented
3. **Concurrent Requests**: Not tested under heavy load
4. **Large Outputs**: May be truncated for very large cell outputs
5. **Streaming**: Cell execution doesn't stream outputs yet

## Next Steps

If all tests pass:
1. Document the setup in main README
2. Create integration tests
3. Test with multiple MCP clients
4. Performance benchmark
5. Security review

If tests fail:
1. Check error messages in logs
2. Verify code is up to date
3. Try with DEBUG logging
4. Report issue with full logs
