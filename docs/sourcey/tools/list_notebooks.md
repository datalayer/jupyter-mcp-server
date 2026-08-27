---
title: "list_notebooks"
description: "List all notebooks that have been used via use_notebook tool"
---

# list_notebooks

List all notebooks that have been used via use_notebook tool

> read-only: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

This tool takes no parameters.

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_notebooks",
    "arguments": {}
  }
}
```

```python
result = await session.call_tool("list_notebooks", arguments={})
```

## Source

Registered by the `@mcp.tool` decorator on `list_notebooks` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

