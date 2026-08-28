---
title: "list_files"
description: "List all files and directories recursively in the Jupyter server's file system."
---

# list_files

List all files and directories recursively in the Jupyter server's file system.
Used to explore the file system structure of the Jupyter server or to find specific files or directories.

> read-only: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `path` | string | no | `""` | The starting path to list from (empty string means root directory) |
| `max_depth` | integer | no | `1` | Maximum depth to recurse into subdirectories |
| `start_index` | integer | no | `0` | Starting index for pagination (0-based) |
| `limit` | integer | no | `25` | Maximum number of items to return (0 means no limit) |
| `pattern` | string | no | `""` | Glob pattern to filter file paths |

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
    },
    "columns": {
      "description": "The header, in order.",
      "items": {
        "type": "string"
      },
      "title": "Columns",
      "type": "array"
    },
    "items": {
      "description": "One object per row, keyed by the header.",
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Items",
      "type": "array"
    },
    "count": {
      "default": 0,
      "description": "How many rows.",
      "title": "Count",
      "type": "integer"
    }
  },
  "required": [
    "kind"
  ],
  "type": "object",
  "additionalProperties": true,
  "description": "A listing that also comes back as rows keyed by its header.",
  "title": "TableAnswer"
}
```

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_files",
    "arguments": {
      "path": "",
      "max_depth": 1,
      "start_index": 0,
      "limit": 25,
      "pattern": ""
    }
  }
}
```

```python
result = await session.call_tool("list_files", arguments={"path": "", "max_depth": 1, "start_index": 0, "limit": 25, "pattern": ""})
```

## Source

Registered by the `@mcp.tool` decorator on `list_files` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

