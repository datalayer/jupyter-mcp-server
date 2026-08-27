---
title: "clear_cell_output"
description: "Clear the outputs and execution count of a single code cell in the currently"
---

# clear_cell_output

Clear the outputs and execution count of a single code cell in the currently
activated notebook, without deleting the cell itself.

> destructive: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer \| null | no | `null` | Index of the code cell to clear (0-based). Omit when passing cell_id. |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |
| `cell_id` | string \| null | no | `null` | Address the cell by its notebook cell id instead of its index. An index is a position, and a position stops being true the moment anyone inserts a cell above it; an id does not. Every result says which id it acted on, so read a cell once and address it by id afterwards. Given both, the id wins. |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "clear_cell_output",
    "arguments": {
      "cell_index": null,
      "notebook_name": null,
      "cell_id": null
    }
  }
}
```

```python
result = await session.call_tool("clear_cell_output", arguments={"cell_index": None, "notebook_name": None, "cell_id": None})
```

## Source

Registered by the `@mcp.tool` decorator on `clear_cell_output` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

