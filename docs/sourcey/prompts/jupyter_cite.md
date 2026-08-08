---
title: jupyter_cite
description: 'Like @ or # in Coding IDE or CLI, cite specific cells from specified notebook and insert them into the prompt.'
---

# jupyter_cite

Like @ or # in Coding IDE or CLI, cite specific cells from specified notebook and insert them into the prompt.

## Arguments

| Argument        | Required | Description                                                                                      |
| --------------- | -------- | ------------------------------------------------------------------------------------------------ |
| `prompt`        | yes      | User prompt for the cited cells                                                                  |
| `cell_indices`  | yes      | Cell indices to cite (0-based),supporting flexible range format, e.g., '0,1,2', '0-2' or '0-2,4' |
| `notebook_name` | no       | Name of the notebook to cite cells from, default (empty) to current activated notebook           |

## Call it

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "prompts/get",
  "params": {
    "name": "jupyter_cite",
    "arguments": {
      "prompt": "<prompt>",
      "cell_indices": "<cell_indices>",
      "notebook_name": "<notebook_name>"
    }
  }
}
```

## Source

Registered by the `@mcp.prompt` decorator on `jupyter_cite` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).
