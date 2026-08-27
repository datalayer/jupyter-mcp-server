---
title: "terminate_sandbox"
description: "Terminate a launched code sandbox."
---

# terminate_sandbox

Terminate a launched code sandbox.

> destructive: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `sandbox_name` | string | yes | — | Sandbox name to terminate and unregister |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "terminate_sandbox",
    "arguments": {
      "sandbox_name": "<sandbox_name>"
    }
  }
}
```

```python
result = await session.call_tool("terminate_sandbox", arguments={"sandbox_name": "<sandbox_name>"})
```

## Source

Registered by the `@mcp.tool` decorator on `terminate_sandbox` in [`ext/sandboxes/jupyter_mcp_sandboxes/extension.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/ext/sandboxes/jupyter_mcp_sandboxes/extension.py).

