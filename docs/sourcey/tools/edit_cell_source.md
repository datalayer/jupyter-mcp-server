---
title: "edit_cell_source"
description: "Perform a surgical find-and-replace within a cell's source (like an editor's Edit tool)."
---

# edit_cell_source

Perform a surgical find-and-replace within a cell's source (like an editor's Edit tool).
Finds `old_string` in the cell and replaces it with `new_string`. Matching is literal
(not regex) and may span multiple lines. By default, `old_string` must appear exactly once;
set `replace_all=True` for multiple occurrences. Returns a diff of the changes made.

Prefer this over overwrite_cell_source for small, targeted edits — it is safer because
unchanged parts of the cell are left untouched. Use read_cell first to see the current
source and construct an accurate old_string.

> destructive: **yes** · idempotent: **no** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer \| null | no | `null` | Index of the cell to edit (0-based). Omit when passing cell_id. |
| `old_string` | string | yes | — | Exact string to find in cell source |
| `new_string` | string | yes | — | Replacement string |
| `replace_all` | boolean | no | `false` | Replace all occurrences (default: first only) |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |
| `cell_id` | string \| null | no | `null` | Address the cell by its notebook cell id instead of its index. An index is a position, and a position stops being true the moment anyone inserts a cell above it; an id does not. Every result says which id it acted on, so read a cell once and address it by id afterwards. Given both, the id wins. |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "edit_cell_source",
    "arguments": {
      "cell_index": null,
      "old_string": "<old_string>",
      "new_string": "<new_string>",
      "replace_all": false,
      "notebook_name": null,
      "cell_id": null
    }
  }
}
```

```python
result = await session.call_tool("edit_cell_source", arguments={"cell_index": None, "old_string": "<old_string>", "new_string": "<new_string>", "replace_all": False, "notebook_name": None, "cell_id": None})
```

## Source

Registered by the `@mcp.tool` decorator on `edit_cell_source` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

