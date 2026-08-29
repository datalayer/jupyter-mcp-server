---
title: "launch_sandbox"
description: "Launch a code sandbox that can be used instead of Jupyter kernels."
---

# launch_sandbox

Launch a code sandbox that can be used instead of Jupyter kernels.

After launch, call use_sandbox to make execute_code run on this sandbox
(as an alternative to notebook-bound kernel execution). Works in both
MCP_SERVER and JUPYTER_SERVER modes.

> destructive: **yes** · idempotent: **no** · open-world: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `sandbox_name` | string | yes | — | Unique sandbox identifier used by list/use/terminate tools |
| `variant` | `eval` · `docker` · `jupyter-server` · `datalayer` · `daytona` · `e2b` · `coreweave` · `cloudflare` · `google-colab` · `kaggle` · `monty` · `modal` \| null | no | `null` | Sandbox variant to launch. If omitted, defaults to configured SANDBOX_VARIANT when it is not jupyter-server; otherwise falls back to eval. |
| `timeout` | integer | no | `60` | Default execution timeout in seconds for this sandbox |
| `environment` | string \| null | no | `null` | Optional sandbox environment name (common for datalayer/modal variants) |
| `gpu` | string \| null | no | `null` | Optional GPU flavor / accelerator. Only coreweave, datalayer, daytona, kaggle and modal have a GPU; asking one of the others (e2b, cloudflare, docker, eval, google-colab, jupyter-server, monty) for a GPU is refused rather than quietly run on a CPU, so leave this unset for them. Examples: modal/datalayer T4, A10G, A100, H100; daytona H100, H200, RTX-4090; coreweave H100; kaggle NvidiaTeslaT4, NvidiaTeslaP100, or the aliases T4/P100. |
| `server_url` | string \| null | no | `null` | Code Sandbox proxy URL when using the google-colab or kaggle variant |
| `kernel_id` | string \| null | no | `null` | Kernel ID when using the google-colab or kaggle variant |
| `proxy_token` | string \| null | no | `null` | Google Colab code sandbox proxy token when using google-colab variant |
| `channels_url` | string \| null | no | `null` | Notebook session WebSocket channels URL to derive server_url/kernel_id (google-colab or kaggle variant) |
| `token` | string \| null | no | `null` | Kaggle API token for the kaggle variant (falls back to KAGGLE_API_TOKEN) |
| `python_version` | string \| null | no | `null` | Modal Python version override (e.g. 3.12). Only used for modal variant. |

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
    "name": "launch_sandbox",
    "arguments": {
      "sandbox_name": "<sandbox_name>",
      "variant": null,
      "timeout": 60,
      "environment": null,
      "gpu": null,
      "server_url": null,
      "kernel_id": null,
      "proxy_token": null,
      "channels_url": null,
      "token": null,
      "python_version": null
    }
  }
}
```

```python
result = await session.call_tool("launch_sandbox", arguments={"sandbox_name": "<sandbox_name>", "variant": None, "timeout": 60, "environment": None, "gpu": None, "server_url": None, "kernel_id": None, "proxy_token": None, "channels_url": None, "token": None, "python_version": None})
```

## Source

Registered by the `@mcp.tool` decorator on `launch_sandbox` in [`extensions/sandboxes/jupyter_mcp_sandboxes/extension.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/extensions/sandboxes/jupyter_mcp_sandboxes/extension.py).

