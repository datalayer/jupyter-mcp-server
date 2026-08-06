---
title: "list_kernels"
description: "List all available kernels in the Jupyter server."
---

# list_kernels

List all available kernels in the Jupyter server.

    This tool shows all running and available kernel sessions on the Jupyter server,
    including their IDs, names, states, connection information, and kernel specifications.
    Useful for monitoring kernel resources and identifying specific kernels for connection.

> read-only: **yes**

## Parameters

This tool takes no parameters.

## Output

```json
{
  "properties": {
    "result": {
      "description": "Tab-separated table with columns: ID, Name, Display_Name, Language, State, Connections, Last_Activity, Environment",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "list_kernelsOutput",
  "type": "object"
}
```

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_kernels",
    "arguments": {}
  }
}
```

```python
result = await session.call_tool("list_kernels", arguments={})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:367`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L367) (commit `c132b061240d`).

