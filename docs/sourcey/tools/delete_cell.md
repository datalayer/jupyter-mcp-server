---
title: "delete_cell"
description: "Delete specific cells from the currently activated notebook and return the cell source of deleted cells (if include_source=True)."
---

# delete_cell

Delete specific cells from the currently activated notebook and return the cell source of deleted cells (if include_source=True).

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_indices` | array<integer> | yes | — | List of cell indices to delete (0-based) |
| `include_source` | boolean | no | `true` | Whether to include the source of deleted cells |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Success message with list of deleted cells and their source (if include_source=True)",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "delete_cellOutput",
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
    "name": "delete_cell",
    "arguments": {
      "cell_indices": "<cell_indices>",
      "include_source": true,
      "notebook_name": null
    }
  }
}
```

```python
result = await session.call_tool("delete_cell", arguments={"cell_indices": "<cell_indices>", "include_source": True, "notebook_name": None})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:853`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L853) (commit `c132b061240d`).

