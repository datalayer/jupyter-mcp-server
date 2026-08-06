---
title: "read_notebook"
description: "Read a notebook and return index, source content, type, execution count of each cell."
---

# read_notebook

Read a notebook and return index, source content, type, execution count of each cell.

    Using brief format to get a quick overview of the notebook structure and it's useful for locating specific cells for operations like delete or insert.
    Using detailed format to get detailed information of the notebook and it's useful for debugging and analysis.

    It is recommended to use brief format with larger limit to get a overview of the notebook structure,
    then use detailed format with exact index and limit to get the detailed information of some specific cells.

> read-only: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `notebook_name` | string | yes | — | Notebook identifier to read |
| `response_format` | `brief` · `detailed` | no | `"brief"` | Response format: 'brief' will return first line and lines number, 'detailed' will return full cell source |
| `start_index` | integer | no | `0` | Starting index for pagination (0-based) |
| `limit` | integer | no | `20` | Maximum number of items to return (0 means no limit) |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Notebook content in the requested format",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "read_notebookOutput",
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
    "name": "read_notebook",
    "arguments": {
      "notebook_name": "<notebook_name>",
      "response_format": "brief",
      "start_index": 0,
      "limit": 20
    }
  }
}
```

```python
result = await session.call_tool("read_notebook", arguments={"notebook_name": "<notebook_name>", "response_format": "brief", "start_index": 0, "limit": 20})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:533`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L533) (commit `c132b061240d`).

