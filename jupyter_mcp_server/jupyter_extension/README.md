# Jupyter to MCP Adapter

This subpackage provides the adapter layer to expose MCP server tools as a Jupyter Server extension.

## Architecture

```
jupyter_extension/
├── context.py          # ServerContext singleton (MCP_SERVER vs JUPYTER_SERVER)
├── extension.py        # JupyterMCPServerExtensionApp
├── handlers.py         # Tornado HTTP handlers for MCP endpoints
├── protocol/
│   └── messages.py     # Pydantic request/response models
├── adapters/
│   └── base.py         # BaseToolAdapter interface
└── backends/
    ├── base.py         # Abstract Backend interface
    ├── remote_backend.py  # Remote Jupyter API access
    └── local_backend.py   # Local serverapp access
```

## Modes of Operation

### MCP_SERVER Mode (Standalone)
- Current default behavior
- Uses Remote Backend
- Connects to Jupyter Server via HTTP/WebSocket
- 100% backward compatible

### JUPYTER_SERVER Mode (Extension)
- New embedded mode
- Can use Local Backend (document_url="local", runtime_url="local")
- Direct access to serverapp.contents_manager and serverapp.kernel_manager
- Or Remote Backend for connecting to other Jupyter servers

## Configuration

### Standalone MCP Server
```bash
jupyter-mcp-server start \
  --document-url http://localhost:8888 \
  --runtime-url http://localhost:8888 \
  --document-token MY_TOKEN \
  --runtime-token MY_TOKEN \
  --port 4040
```

### Jupyter Server Extension (Local Access)
```bash
jupyter server \
  --JupyterMCPServerExtensionApp.document_url=local \
  --JupyterMCPServerExtensionApp.runtime_url=local \
  --JupyterMCPServerExtensionApp.document_id=notebook.ipynb \
  --port=4040 \
  --token=MY_TOKEN
```

MCP endpoints available at: `http://localhost:4040/mcp/`

### Jupyter Server Extension (Remote Access)
```python
# jupyter_server_config.py
c.JupyterMCPServerExtensionApp.document_url = "http://other-jupyter:8888"
c.JupyterMCPServerExtensionApp.runtime_url = "http://other-jupyter:8888"
c.JupyterMCPServerExtensionApp.document_token = "REMOTE_TOKEN"
c.JupyterMCPServerExtensionApp.runtime_token = "REMOTE_TOKEN"
```

## Endpoints

When running as Jupyter Server extension:

- `GET /mcp/healthz` - Health check
- `GET /mcp/tools/list` - List available tools
- `POST /mcp/tools/call` - Execute a tool
- `GET /mcp/sse` - Server-Sent Events (real-time updates)

## Development Status

This is the initial implementation establishing the architecture. Current status:

- ✅ Context management (MCP_SERVER vs JUPYTER_SERVER)
- ✅ Backend interface defined
- ✅ Local Backend implemented (direct serverapp access)
- ✅ Remote Backend structure (delegates to existing server.py for now)
- ✅ Jupyter Server Extension with handlers
- ✅ Auto-enable configuration
- ✅ Dependencies updated
- ⏳ Tool adapters (next phase)
- ⏳ Full RemoteBackend refactoring (next phase)
- ⏳ Integration with existing server.py tools (next phase)

## Next Steps

1. Implement BaseToolAdapter and tool-specific adapters
2. Refactor existing server.py tools to use adapters
3. Complete RemoteBackend by extracting logic from server.py
4. Add comprehensive tests for both modes
5. Update NotebookManager for backend awareness

## Testing

```bash
# Test standalone mode (should work as before)
make start

# Test extension mode with local access
make start-as-jupyter-server

# Check health
curl http://localhost:4040/mcp/healthz

# List tools
curl http://localhost:4040/mcp/tools/list
```
