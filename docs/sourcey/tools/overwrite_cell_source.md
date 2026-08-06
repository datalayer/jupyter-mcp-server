---
title: "overwrite_cell_source"
description: "Replace the entire source of a cell in the currently activated notebook."
---

# overwrite_cell_source

Replace the entire source of a cell in the currently activated notebook.
    Returns a diff showing the changes made.

    Use this when rewriting a cell completely. For small, targeted changes,
    prefer edit_cell_source instead — it is safer for partial edits.

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer | yes | — | Index of the cell to overwrite (0-based) |
| `cell_source` | string | yes | — | New complete cell source |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Success message with diff showing changes made",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "overwrite_cell_sourceOutput",
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
    "name": "overwrite_cell_source",
    "arguments": {
      "cell_index": 0,
      "cell_source": "<cell_source>",
      "notebook_name": null
    }
  }
}
```

```python
result = await session.call_tool("overwrite_cell_source", arguments={"cell_index": 0, "cell_source": "<cell_source>", "notebook_name": None})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:620`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L620) (commit `c132b061240d`).

