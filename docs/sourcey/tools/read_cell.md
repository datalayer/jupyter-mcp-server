---
title: "read_cell"
description: "Read a cell as readable text entries."
---

# read_cell

Read a cell as readable text entries.

Includes metadata and source, plus optional formatted output text rather
than raw nbformat objects.

> read-only: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer | yes | — | Index of the cell to read (0-based) |
| `include_outputs` | boolean | no | `true` | Include outputs in the response (only for code cells) |
| `notebook_name` | string \| null | no | `null` | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "read_cell",
    "arguments": {
      "cell_index": 0,
      "include_outputs": true,
      "notebook_name": null
    }
  }
}
```

```python
result = await session.call_tool("read_cell", arguments={"cell_index": 0, "include_outputs": True, "notebook_name": None})
```

## Source

Registered by the `@mcp.tool` decorator on `read_cell` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

