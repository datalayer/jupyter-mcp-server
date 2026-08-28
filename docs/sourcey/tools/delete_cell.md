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

