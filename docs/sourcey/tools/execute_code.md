---
title: "execute_code"
description: "Execute code directly in a kernel (not saved to notebook)."
---

# execute_code

Execute code directly in a kernel (not saved to notebook).

If `use_sandbox` selected an active sandbox, this tool executes on that
sandbox instead of a Jupyter kernel. This allows agents to switch between
kernel-backed and sandbox-backed execution using the same execute_code API.

Targets the current activated notebook's kernel by default. Pass kernel_id
to execute in a specific kernel directly — including raw kernels with no
notebook attached.

Recommended to use in following cases:
1. Execute Jupyter magic commands(e.g., `%timeit`, `%pip install xxx`)
2. Performance profiling and debugging.
3. View intermediate variable values(e.g., `print(xxx)`, `df.head()`)
4. Temporary calculations and quick tests(e.g., `np.mean(df['xxx'])`)
5. Execute Shell commands in Jupyter server(e.g., `!git xxx`)

Under no circumstances should you use this tool to:
1. Import new modules or perform variable assignments that affect subsequent Notebook execution
2. Execute dangerous code that may harm the Jupyter server or the user's data without permission

> destructive: **yes** · idempotent: **no** · open-world: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `code` | string | yes | — | Code to execute (supports magic commands with %, shell commands with !) |
| `timeout` | integer | no | `30` | Maximum seconds to wait for execution (0 = use config default) |
| `kernel_id` | string \| null | no | `null` | Target an existing kernel by ID (e.g. a raw kernel with no notebook). If omitted, uses the current notebook's kernel. |
| `progress_interval` | integer | no | `5` | Seconds between MCP progress keepalive updates during long-running execution |

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
    "name": "execute_code",
    "arguments": {
      "code": "<code>",
      "timeout": 30,
      "kernel_id": null,
      "progress_interval": 5
    }
  }
}
```

```python
result = await session.call_tool("execute_code", arguments={"code": "<code>", "timeout": 30, "kernel_id": None, "progress_interval": 5})
```

## Source

Registered by the `@mcp.tool` decorator on `execute_code` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

