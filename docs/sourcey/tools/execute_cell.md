---
title: "execute_cell"
description: "Execute a cell from the currently activated notebook with timeout and return it's outputs"
---

# execute_cell

Execute a cell from the currently activated notebook with timeout and return it's outputs

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer | yes | — | Index of the cell to execute (0-based) |
| `timeout` | integer | no | `0` | Maximum seconds to wait for execution (0 = use config default) |
| `stream` | boolean | no | `false` | Enable streaming progress (including time indicator) updates for long-running cells |
| `progress_interval` | integer | no | `5` | Seconds between progress updates when stream=True |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "execute_cell",
    "arguments": {
      "cell_index": 0,
      "timeout": 0,
      "stream": false,
      "progress_interval": 5
    }
  }
}
```

```python
result = await session.call_tool("execute_cell", arguments={"cell_index": 0, "timeout": 0, "stream": False, "progress_interval": 5})
```

## Source

Registered by the `@mcp.tool` decorator at [`jupyter_mcp_server/server.py:700`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server.py#L700) (commit `c132b061240d`).

