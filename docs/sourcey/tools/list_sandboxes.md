---
title: "list_sandboxes"
description: "List launched code sandboxes that can be used as alternatives to kernels."
---

# list_sandboxes

List launched code sandboxes that can be used as alternatives to kernels.

> read-only: **yes**

## Parameters

This tool takes no parameters.

## Output

```json
{
  "properties": {
    "result": {
      "description": "All launched sandboxes with name, variant, status, and active flag",
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Result",
      "type": "array"
    }
  },
  "required": [
    "result"
  ],
  "title": "list_sandboxesOutput",
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
    "name": "list_sandboxes",
    "arguments": {}
  }
}
```

```python
result = await session.call_tool("list_sandboxes", arguments={})
```

## Source

Registered by the `@mcp.tool` decorator at [`ext/sandboxes/jupyter_mcp_sandboxes/extension.py:204`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/ext/sandboxes/jupyter_mcp_sandboxes/extension.py#L204) (commit `c132b061240d`).

