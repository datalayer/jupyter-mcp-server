---
title: "execute_cell"
description: "Execute a cell from the currently activated notebook with timeout and return it's outputs"
---

# execute_cell

Execute a cell from the currently activated notebook with timeout and return it's outputs

> destructive: **yes** · idempotent: **no** · open-world: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cell_index` | integer \| null | no | `null` | Index of the cell to execute (0-based). Omit when passing cell_id. |
| `timeout` | integer | no | `0` | Maximum seconds to wait for execution (0 = use config default) |
| `stream` | boolean | no | `true` | Enable streaming progress (including time indicator) updates for long-running cells |
| `progress_interval` | integer | no | `5` | Seconds between progress updates (MCP keepalive + optional stream log) |
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
    },
    "outputs": {
      "description": "The outputs in order: text as text, an image as its own object.",
      "items": {},
      "title": "Outputs",
      "type": "array"
    },
    "count": {
      "default": 0,
      "description": "How many outputs.",
      "title": "Count",
      "type": "integer"
    },
    "images": {
      "default": 0,
      "description": "How many of them are images.",
      "title": "Images",
      "type": "integer"
    }
  },
  "required": [
    "kind"
  ],
  "type": "object",
  "additionalProperties": true,
  "description": "Cell or execution outputs, in order.",
  "title": "OutputsAnswer"
}
```

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "execute_cell",
    "arguments": {
      "cell_index": null,
      "timeout": 0,
      "stream": true,
      "progress_interval": 5,
      "cell_id": null
    }
  }
}
```

```python
result = await session.call_tool("execute_cell", arguments={"cell_index": None, "timeout": 0, "stream": True, "progress_interval": 5, "cell_id": None})
```

## Source

Registered by the `@mcp.tool` decorator on `execute_cell` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

