---
title: "restart_notebook"
description: "Restart the kernel for a specific notebook."
---

# restart_notebook

Restart the kernel for a specific notebook.

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `notebook_name` | string | yes | — | Notebook identifier to restart |

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
  "title": "restart_notebookOutput",
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
    "name": "restart_notebook",
    "arguments": {
      "notebook_name": "<notebook_name>"
    }
  }
}
```

```python
result = await session.call_tool("restart_notebook", arguments={"notebook_name": "<notebook_name>"})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:479`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L479) (commit `c132b061240d`).

