---
title: "move_cell"
description: "Move a cell from source_index to target_index within the currently activated notebook."
---

# move_cell

Move a cell from source_index to target_index within the currently activated notebook.

    The cell is removed from source_index and placed at target_index. Cells in between shift
    to fill the gap. The cell's type, source, and outputs are preserved.
    Example: in a notebook [A, B, C, D], move_cell(1, 3) produces [A, C, D, B].

    Use this tool instead of manually deleting and re-inserting a cell — it is atomic and
    preserves cell metadata. Use read_notebook first to see cell indices if needed.

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source_index` | integer | yes | — | Index of the cell to move (0-based) |
| `target_index` | integer | yes | — | Destination index where the cell will end up (0-based) |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Success message with moved cell info and surrounding context",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "move_cellOutput",
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
    "name": "move_cell",
    "arguments": {
      "source_index": 0,
      "target_index": 0,
      "notebook_name": null
    }
  }
}
```

```python
result = await session.call_tool("move_cell", arguments={"source_index": 0, "target_index": 0, "notebook_name": None})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:927`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L927) (commit `c132b061240d`).

