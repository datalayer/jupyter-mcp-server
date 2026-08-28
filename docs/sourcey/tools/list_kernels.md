---
title: "list_kernels"
description: "List all available kernels in the Jupyter server."
---

# list_kernels

List all available kernels in the Jupyter server.

This tool shows all running and available kernel sessions on the Jupyter server,
including their IDs, names, states, connection information, and kernel specifications.
Useful for monitoring kernel resources and identifying specific kernels for connection.

> read-only: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

This tool takes no parameters.

## Output

```json
{
  "properties": {
    "kind": {
      "description": "What this result is — 'cell.read', 'notebooks.list' and so on. Lets a client tell one answer from another without matching prose.",
      "title": "Kind",
      "type": "string"
    },
    "result": {
      "default": null,
      "description": "The answer itself: a message, the rows of a listing, or the outputs of an execution in order.",
      "title": "Result"
    },
    "columns": {
      "description": "The header, in order.",
      "items": {
        "type": "string"
      },
      "title": "Columns",
      "type": "array"
    },
    "items": {
      "description": "One object per row, keyed by the header.",
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Items",
      "type": "array"
    },
    "count": {
      "default": 0,
      "description": "How many rows.",
      "title": "Count",
      "type": "integer"
    }
  },
  "required": [
    "kind"
  ],
  "type": "object",
  "additionalProperties": true,
  "description": "A listing that also comes back as rows keyed by its header.",
  "title": "TableAnswer"
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

Registered by the `@mcp.tool` decorator on `list_kernels` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

