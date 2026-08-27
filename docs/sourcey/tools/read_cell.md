---
title: "read_cell"
description: "Read a cell as readable text entries."
---

# read_cell

Read a cell as readable text entries.

Includes metadata and source, plus optional formatted output text rather
than raw nbformat objects.

> read-only: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer \| null | no | `null` | Index of the cell to read (0-based). Omit when passing cell_id. |
| `include_outputs` | boolean | no | `true` | Include outputs in the response (only for code cells) |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |
| `cell_id` | string \| null | no | `null` | Address the cell by its notebook cell id instead of its index. An index is a position, and a position stops being true the moment anyone inserts a cell above it; an id does not. Every result says which id it acted on, so read a cell once and address it by id afterwards. Given both, the id wins. |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "read_cell",
    "arguments": {
      "cell_index": null,
      "include_outputs": true,
      "notebook_name": null,
      "cell_id": null
    }
  }
}
```

```python
result = await session.call_tool("read_cell", arguments={"cell_index": None, "include_outputs": True, "notebook_name": None, "cell_id": None})
```

## Source

Registered by the `@mcp.tool` decorator on `read_cell` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

