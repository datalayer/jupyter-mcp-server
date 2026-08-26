---
title: "connect_to_jupyter"
description: "Connect to a Jupyter server dynamically with URL and token."
---

# connect_to_jupyter

Connect to a Jupyter server dynamically with URL and token.

This tool allows you to connect to different Jupyter servers without needing to
restart the MCP server or modify configuration files. Particularly useful when:
- Working with multiple Jupyter servers with different ports/tokens
- Jupyter server token changes dynamically
- Need to switch between different Jupyter instances

Example usage:
- "Connect to http://localhost:8888 with token abc123"
- "Connect to http://localhost:8889 without authentication"

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `jupyter_url` | string | yes | — | Jupyter server URL to connect to (e.g., 'http://localhost:8888') |
| `jupyter_token` | string \| null | no | `null` | Jupyter server authentication token |
| `document_provider` | string | no | `"jupyter"` | Which backend holds the notebook documents |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Connection status message",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "type": "object",
  "title": "connect_to_jupyterOutput"
}
```

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "connect_to_jupyter",
    "arguments": {
      "jupyter_url": "<jupyter_url>",
      "jupyter_token": null,
      "document_provider": "jupyter"
    }
  }
}
```

```python
result = await session.call_tool("connect_to_jupyter", arguments={"jupyter_url": "<jupyter_url>", "jupyter_token": None, "document_provider": "jupyter"})
```

## Source

Registered by the `@mcp.tool` decorator on `connect_to_jupyter` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

