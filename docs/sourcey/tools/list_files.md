---
title: "list_files"
description: "List all files and directories recursively in the Jupyter server's file system."
---

# list_files

List all files and directories recursively in the Jupyter server's file system.
Used to explore the file system structure of the Jupyter server or to find specific files or directories.

> read-only: **yes**

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
    "result": {
      "description": "Tab-separated table with columns: Path, Type, Size, Last_Modified. Includes pagination info header.",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "type": "object",
  "title": "list_filesOutput"
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

