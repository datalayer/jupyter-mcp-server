---
title: "insert_cell"
description: "Insert a cell to specified position from the currently activated notebook."
---

# insert_cell

Insert a cell to specified position from the currently activated notebook.

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer | yes | — | Target index for insertion (0-based), use -1 to append at end |
| `cell_type` | `code` · `markdown` | yes | — | Type of cell to insert |
| `cell_source` | string | yes | — | Source content for the cell |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Success message and the structure of its surrounding cells",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "insert_cellOutput",
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
    "name": "insert_cell",
    "arguments": {
      "cell_index": 0,
      "cell_type": "<cell_type>",
      "cell_source": "<cell_source>",
      "notebook_name": null
    }
  }
}
```

```python
result = await session.call_tool("insert_cell", arguments={"cell_index": 0, "cell_type": "<cell_type>", "cell_source": "<cell_source>", "notebook_name": None})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:581`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L581) (commit `c132b061240d`).

