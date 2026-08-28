---
title: "overwrite_cell_source"
description: "Replace the entire source of a cell in the currently activated notebook."
---

# overwrite_cell_source

Replace the entire source of a cell in the currently activated notebook.
Returns a diff showing the changes made.

Use this when rewriting a cell completely. For small, targeted changes,
prefer edit_cell_source instead — it is safer for partial edits.

> destructive: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer \| null | no | `null` | Index of the cell to overwrite (0-based). Omit when passing cell_id. |
| `cell_source` | string | yes | — | New complete cell source |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |
| `cell_id` | string \| null | no | `null` | Address the cell by its notebook cell id instead of its index. An index is a position, and a position stops being true the moment anyone inserts a cell above it; an id does not. Every result says which id it acted on, so read a cell once and address it by id afterwards. Given both, the id wins. |

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
    "name": "overwrite_cell_source",
    "arguments": {
      "cell_index": null,
      "cell_source": "<cell_source>",
      "notebook_name": null,
      "cell_id": null
    }
  }
}
```

```python
result = await session.call_tool("overwrite_cell_source", arguments={"cell_index": None, "cell_source": "<cell_source>", "notebook_name": None, "cell_id": None})
```

## Source

Registered by the `@mcp.tool` decorator on `overwrite_cell_source` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

