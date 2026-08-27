---
title: "delete_cell"
description: "Delete specific cells from the currently activated notebook and return the cell source of deleted cells (if include_source=True)."
---

# delete_cell

Delete specific cells from the currently activated notebook and return the cell source of deleted cells (if include_source=True).

> destructive: **yes** · idempotent: **no** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_indices` | array<integer> \| null | no | `null` | List of cell indices to delete (0-based). Omit when passing cell_ids_to_delete. |
| `include_source` | boolean | no | `true` | Whether to include the source of deleted cells |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |
| `cell_ids_to_delete` | array<string> \| null | no | `null` | Address the cells by their notebook cell ids instead of their indices. Safer for a multi-cell delete than indices, which shift as earlier cells go. Given both, the ids win; every id is checked before any cell is deleted, so a bad one fails the whole call rather than half-deleting the notebook. |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "delete_cell",
    "arguments": {
      "cell_indices": null,
      "include_source": true,
      "notebook_name": null,
      "cell_ids_to_delete": null
    }
  }
}
```

```python
result = await session.call_tool("delete_cell", arguments={"cell_indices": None, "include_source": True, "notebook_name": None, "cell_ids_to_delete": None})
```

## Source

Registered by the `@mcp.tool` decorator on `delete_cell` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

