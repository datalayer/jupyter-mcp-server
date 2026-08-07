---
title: "insert_execute_code_cell"
description: "Insert a cell at specified index from the currently activated notebook and then execute it with timeout and return it's outputs"
---

# insert_execute_code_cell

Insert a cell at specified index from the currently activated notebook and then execute it with timeout and return it's outputs
It is a shortcut tool for insert_cell and execute_cell tools, recommended to use if you want to insert a cell and execute it at the same time

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer | yes | — | Index of the cell to insert and execute (0-based) |
| `cell_source` | string | yes | — | Code source for the cell |
| `timeout` | integer | no | `0` | Maximum seconds to wait for execution (0 = use config default) |
| `stream` | boolean | no | `true` | Enable streaming progress (including time indicator) updates for long-running cells |
| `progress_interval` | integer | no | `5` | Seconds between progress updates (MCP keepalive + optional stream log) |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "insert_execute_code_cell",
    "arguments": {
      "cell_index": 0,
      "cell_source": "<cell_source>",
      "timeout": 0,
      "stream": true,
      "progress_interval": 5
    }
  }
}
```

```python
result = await session.call_tool("insert_execute_code_cell", arguments={"cell_index": 0, "cell_source": "<cell_source>", "timeout": 0, "stream": True, "progress_interval": 5})
```

## Source

Registered by the `@mcp.tool` decorator on `insert_execute_code_cell` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

