---
title: "launch_sandbox"
description: "Launch a code sandbox that can be used instead of Jupyter kernels."
---

# launch_sandbox

Launch a code sandbox that can be used instead of Jupyter kernels.

After launch, call use_sandbox to make execute_code run on this sandbox
(as an alternative to notebook-bound kernel execution). Works in both
MCP_SERVER and JUPYTER_SERVER modes.

> destructive: **yes**

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `sandbox_name` | string | yes | — | Unique sandbox identifier used by list/use/terminate tools |
| `variant` | `eval` · `docker` · `jupyter` · `datalayer` · `google_colab` · `google-colab` · `colab` · `kaggle` · `monty` · `modal` \| null | no | `null` | Sandbox variant to launch. If omitted, defaults to configured SANDBOX_VARIANT when it is non-jupyter; otherwise falls back to eval. |
| `timeout` | integer | no | `60` | Default execution timeout in seconds for this sandbox |
| `environment` | string \| null | no | `null` | Optional sandbox environment name (common for datalayer/modal variants) |
| `gpu` | string \| null | no | `null` | Optional GPU flavor / accelerator for supported variants (modal/datalayer examples: T4, A10G, A100, H100; kaggle examples: NvidiaTeslaT4, NvidiaTeslaP100, or aliases T4/P100). |
| `server_url` | string \| null | no | `null` | Code Sandbox proxy URL when using google_colab/google-colab (or legacy colab) or kaggle variant |
| `kernel_id` | string \| null | no | `null` | Kernel ID when using google_colab/google-colab (or legacy colab) or kaggle variant |
| `proxy_token` | string \| null | no | `null` | Google Colab code sandbox proxy token when using google_colab/google-colab (or legacy colab) variant |
| `channels_url` | string \| null | no | `null` | Notebook session WebSocket channels URL to derive server_url/kernel_id (google_colab/google-colab/colab or kaggle variant) |
| `token` | string \| null | no | `null` | Datalayer API token override, or Kaggle API token for the kaggle variant (falls back to KAGGLE_API_TOKEN) |
| `run_url` | string \| null | no | `null` | Datalayer run URL override |
| `python_version` | string \| null | no | `null` | Modal Python version override (e.g. 3.12). Only used for modal variant. |

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
      "run_url": null,
      "python_version": null
    }
  }
}
```

```python
result = await session.call_tool("launch_sandbox", arguments={"sandbox_name": "<sandbox_name>", "variant": None, "timeout": 60, "environment": None, "gpu": None, "server_url": None, "kernel_id": None, "proxy_token": None, "channels_url": None, "token": None, "run_url": None, "python_version": None})
```

## Source

Registered by the `@mcp.tool` decorator on `launch_sandbox` in [`ext/sandboxes/jupyter_mcp_sandboxes/extension.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/ext/sandboxes/jupyter_mcp_sandboxes/extension.py).

