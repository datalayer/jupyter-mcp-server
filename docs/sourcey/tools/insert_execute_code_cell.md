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
      "timeout": 0
    }
  }
}
```

```python
result = await session.call_tool("insert_execute_code_cell", arguments={"cell_index": 0, "cell_source": "<cell_source>", "timeout": 0})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:749`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L749) (commit `c132b061240d`).

