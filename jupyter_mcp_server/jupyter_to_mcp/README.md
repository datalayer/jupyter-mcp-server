# Jupyter-to-MCP HTTP Adapter

This extension provides HTTP REST API endpoints that expose MCP (Model Context Protocol) tools through standard HTTP requests, acting as an adapter between HTTP clients and the MCP protocol.

## Features

- **Protocol Translation**: Converts HTTP REST requests to MCP JSON-RPC calls
- **Session Management**: Handles MCP session lifecycle transparently
- **Error Handling**: Maps MCP errors to appropriate HTTP status codes
- **CORS Support**: Enables cross-origin requests for web clients
- **Authentication**: Integrates with Jupyter's authentication system

## Endpoints

### Base URL
All endpoints are available under `/mcp` by default (configurable).

### Initialize & Capabilities
- `GET /mcp/initialize` - Get initialization information
- `POST /mcp/initialize` - Initialize MCP session
- `GET /mcp/capabilities` - Get server capabilities

### Tools
- `GET /mcp/tools/list` - List available MCP tools
- `POST /mcp/tools/call` - Call an MCP tool

### Utilities  
- `GET /mcp/health` - Health check endpoint

## API Examples

### 1. Health Check
```bash
curl http://localhost:8888/mcp/health
```

### 2. Initialize Session
```bash
curl -X POST http://localhost:8888/mcp/initialize \
  -H "Content-Type: application/json" \
  -d '{
    "protocolVersion": "2025-03-26",
    "capabilities": {"tools": {}},
    "clientInfo": {"name": "my-client", "version": "1.0.0"}
  }'
```

### 3. List Available Tools
```bash
curl http://localhost:8888/mcp/tools/list \
  -H "X-Session-ID: your-session-id"
```

### 4. Call a Tool
```bash
curl -X POST http://localhost:8888/mcp/tools/call \
  -H "Content-Type: application/json" \
  -H "X-Session-ID: your-session-id" \
  -d '{
    "name": "list_cell",
    "arguments": {}
  }'
```

### 5. Insert and Execute Code Cell
```bash
curl -X POST http://localhost:8888/mcp/tools/call \
  -H "Content-Type: application/json" \
  -H "X-Session-ID: your-session-id" \
  -d '{
    "name": "insert_execute_code_cell",
    "arguments": {
      "cell_index": -1,
      "cell_source": "print(\"Hello from HTTP API!\")"
    }
  }'
```

## Configuration

The extension can be configured through Jupyter server configuration:

```python
# jupyter_server_config.py
c.JupyterToMCPExtension.enabled = True
c.JupyterToMCPExtension.mcp_server_url = "http://localhost:4040"
c.JupyterToMCPExtension.base_path = "/mcp"
c.JupyterToMCPExtension.session_timeout = 3600
```

## Session Management

The adapter uses session IDs to maintain state between HTTP requests:

- Include `X-Session-ID` header in requests
- If not provided, a new session ID is generated
- Sessions are maintained in memory and have configurable timeouts

## Error Handling

HTTP status codes are mapped from MCP errors:
- `400 Bad Request` - Invalid request format or parameters
- `404 Not Found` - Tool not found
- `409 Conflict` - Tool execution error
- `500 Internal Server Error` - Server errors
- `503 Service Unavailable` - MCP server not available

## Security Considerations

- Inherits Jupyter's authentication system
- All endpoints require authentication by default
- CORS headers are configurable
- Input validation on all requests
- Session timeouts prevent resource leaks

## Installation

The extension is automatically enabled when the `jupyter_mcp_server` package is installed. To manually enable/disable:

```bash
# Enable
jupyter server extension enable jupyter_mcp_server.jupyter_to_mcp

# Disable  
jupyter server extension disable jupyter_mcp_server.jupyter_to_mcp
```
