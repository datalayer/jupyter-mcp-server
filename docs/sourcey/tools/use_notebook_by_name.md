---
title: "use_notebook_by_name"
description: "Switch the active notebook to an already-connected notebook by its registered name."
---

# use_notebook_by_name

Switch the active notebook to an already-connected notebook by its registered name.
Use use_notebook first to connect a notebook by notebook_path (optionally giving it a
notebook_name), then call use_notebook_by_name to switch back to it without repeating
the path.

> destructive: **no** · idempotent: **yes** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `notebook_name` | string | yes | — | Identifier of an already-connected notebook to activate (registered earlier via use_notebook). |

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
    }
  },
  "required": [
    "kind"
  ],
  "type": "object",
  "additionalProperties": true,
  "description": "What every tool of this server answers with.\n\nDeclared so the shape is *advertised* rather than merely produced. A tool\nthat returns structure without saying what it will return leaves a client\nnothing to validate against and the generated reference nothing to show —\nthe call works and the contract is invisible, which is the worst of both.\n\nExtra fields are allowed on purpose. A tool that already answers with a\nmapping keeps its own keys (see :func:`_default_shape`), and those are the\ninteresting part of its answer; forbidding them would mean either\nflattening every tool into one shape or declaring nothing at all.",
  "title": "ToolAnswer"
}
```

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "use_notebook_by_name",
    "arguments": {
      "notebook_name": "<notebook_name>"
    }
  }
}
```

```python
result = await session.call_tool("use_notebook_by_name", arguments={"notebook_name": "<notebook_name>"})
```

## Source

Registered by the `@mcp.tool` decorator on `use_notebook_by_name` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

