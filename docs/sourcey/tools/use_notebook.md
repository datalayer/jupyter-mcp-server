---
title: "use_notebook"
description: "Use a notebook and activate it for following cell operations."
---

# use_notebook

Use a notebook and activate it for following cell operations.
    All cell operations will be performed on the currently activated notebook.
    Activate new notebook will deactivate the previously activated notebook.
    Reactivate previously activated notebook using same notebook_name and notebook_path.

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `notebook_name` | string | yes | — | Unique identifier for the notebook |
| `notebook_path` | string | yes | — | Path to the notebook file, relative to the Jupyter server root (e.g. 'notebook.ipynb') |
| `mode` | `connect` · `create` | no | `"connect"` | Notebook operation mode: 'connect' to connect to existing and activate it, 'create' to create new and activate it |
| `kernel_id` | string | no | `null` | Specific kernel ID to use (will create new if skipped) |

## Output

```json
{
  "properties": {
    "result": {
      "description": "Success message with notebook information",
      "title": "Result",
      "type": "string"
    }
  },
  "required": [
    "result"
  ],
  "title": "use_notebookOutput",
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
    "name": "use_notebook",
    "arguments": {
      "notebook_name": "<notebook_name>",
      "notebook_path": "<notebook_path>",
      "mode": "connect",
      "kernel_id": null
    }
  }
}
```

```python
result = await session.call_tool("use_notebook", arguments={"notebook_name": "<notebook_name>", "notebook_path": "<notebook_path>", "mode": "connect", "kernel_id": None})
```

## Source

Registered by the `@mcp.tool` decorator on `use_notebook` in [`jupyter_mcp_server/server.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server.py).

