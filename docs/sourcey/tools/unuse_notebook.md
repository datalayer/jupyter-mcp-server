---
title: "unuse_notebook"
description: "Unuse from a specific notebook and release its resources."
---

# unuse_notebook

Unuse from a specific notebook and release its resources.

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `notebook_name` | string | yes | — | Notebook identifier to disconnect |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Success message",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "type": "object",
  "title": "unuse_notebookOutput"
}
```

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "unuse_notebook",
    "arguments": {
      "notebook_name": "<notebook_name>"
    }
  }
}
```

```python
result = await session.call_tool("unuse_notebook", arguments={"notebook_name": "<notebook_name>"})
```

## Source

Registered by the `@mcp.tool` decorator on `unuse_notebook` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

