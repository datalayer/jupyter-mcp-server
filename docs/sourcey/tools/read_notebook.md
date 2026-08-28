---
title: "read_notebook"
description: "Read a notebook and return index, source content, type, execution count of each cell."
---

# read_notebook

Read a notebook and return index, source content, type, execution count of each cell.

Using brief format to get a quick overview of the notebook structure and it's useful for locating specific cells for operations like delete or insert.
Using detailed format to get detailed information of the notebook and it's useful for debugging and analysis.

It is recommended to use brief format with larger limit to get a overview of the notebook structure,
then use detailed format with exact index and limit to get the detailed information of some specific cells.

> read-only: **yes** · idempotent: **yes** · open-world: **no**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `notebook_name` | string | yes | — | Notebook identifier to read |
| `response_format` | `brief` · `detailed` | no | `"brief"` | Response format: 'brief' will return first line and lines number, 'detailed' will return full cell source |
| `start_index` | integer | no | `0` | Starting index for pagination (0-based) |
| `limit` | integer | no | `20` | Maximum number of items to return (0 means no limit) |

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
    "name": "read_notebook",
    "arguments": {
      "notebook_name": "<notebook_name>",
      "response_format": "brief",
      "start_index": 0,
      "limit": 20
    }
  }
}
```

```python
result = await session.call_tool("read_notebook", arguments={"notebook_name": "<notebook_name>", "response_format": "brief", "start_index": 0, "limit": 20})
```

## Source

Registered by the `@mcp.tool` decorator on `read_notebook` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

