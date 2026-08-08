---
title: clear_cell_output
description: Clear the outputs and execution count of a single code cell in the currently
---

# clear_cell_output

Clear the outputs and execution count of a single code cell in the currently
activated notebook, without deleting the cell itself.

> destructive: **yes**

## Parameters

| Parameter       | Type           | Required | Default | Description                                                                                                                                                                                                                       |
| --------------- | -------------- | -------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cell_index`    | integer        | yes      | —       | Index of the code cell to clear (0-based)                                                                                                                                                                                         |
| `notebook_name` | string \| null | no       | `null`  | Target this specific connected notebook instead of the currently activated one. Use when multiple clients share this server, to avoid racing the shared 'current notebook' pointer. Omit to use the currently activated notebook. |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Success message with the number of outputs removed",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "clear_cell_outputOutput",
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
    "name": "clear_cell_output",
    "arguments": {
      "cell_index": 0,
      "notebook_name": null
    }
  }
}
```

```python
result = await session.call_tool("clear_cell_output", arguments={"cell_index": 0, "notebook_name": None})
```

## Source

Registered by the `@mcp.tool` decorator on `clear_cell_output` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).
