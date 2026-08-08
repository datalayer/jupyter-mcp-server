---
title: use_sandbox
description: Select which launched sandbox execute_code should use instead of kernels.
---

# use_sandbox

Select which launched sandbox execute_code should use instead of kernels.

> destructive: **yes**

## Parameters

| Parameter      | Type           | Required | Default | Description                                                                                                          |
| -------------- | -------------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------------- |
| `sandbox_name` | string \| null | no       | `null`  | Sandbox name to activate for execute_code. Pass null/empty to disable sandbox routing and return to Jupyter kernels. |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Sandbox routing status",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "use_sandboxOutput",
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
    "name": "use_sandbox",
    "arguments": {
      "sandbox_name": null
    }
  }
}
```

```python
result = await session.call_tool("use_sandbox", arguments={"sandbox_name": None})
```

## Source

Registered by the `@mcp.tool` decorator on `use_sandbox` in [`ext/sandboxes/jupyter_mcp_sandboxes/extension.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/ext/sandboxes/jupyter_mcp_sandboxes/extension.py).
