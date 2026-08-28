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

> destructive: **yes** · idempotent: **no** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `source_index` | integer \| null | no | `null` | Index of the cell to move (0-based). Omit when passing source_cell_id. |
| `target_index` | integer \| null | no | `null` | Destination index where the cell will end up (0-based). Omit when passing target_cell_id. |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |
| `source_cell_id` | string \| null | no | `null` | Address the cell to move by its id rather than its index. |
| `target_cell_id` | string \| null | no | `null` | Put the moved cell where this cell is now, addressed by id rather than by an index that the move itself will shift. |

## Output

```json
{
  "properties": {
    "kind": {
      "description": "What this result is — 'cell.read', 'notebooks.list' and so on. Lets a client tell one answer from another without matching prose.",
      "title": "Kind",
      "type": "string"
    },
    "result": {
      "default": null,
      "description": "The answer itself: a message, the rows of a listing, or the outputs of an execution in order.",
      "title": "Result"
    }
  },
  "required": [
    "kind"
  ],
  "type": "object",
  "additionalProperties": true,
  "description": "What every tool of this server answers with.\n\nDeclared so the shape is *advertised* rather than merely produced. A tool\nthat returns structure without saying what it will return leaves a client\nnothing to validate against and the generated reference nothing to show —\nthe call works and the contract is invisible, which is the worst of both.\n\nExtra fields are allowed on purpose. A tool that already answers with a\nmapping keeps its own keys (see :func:`_default_shape`), and those are the\ninteresting part of its answer; forbidding them would mean either\nflattening every tool into one shape or declaring nothing at all.",
  "title": "ToolAnswer"
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
      "source_index": null,
      "target_index": null,
      "notebook_name": null,
      "source_cell_id": null,
      "target_cell_id": null
    }
  }
}
```

```python
result = await session.call_tool("move_cell", arguments={"source_index": None, "target_index": None, "notebook_name": None, "source_cell_id": None, "target_cell_id": None})
```

## Source

Registered by the `@mcp.tool` decorator on `move_cell` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

