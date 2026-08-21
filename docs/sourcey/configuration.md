---
title: "Configuration"
description: "Every setting of JupyterMCPConfig, generated from the pydantic model in the source tree."
---

# Configuration

All runtime settings live on the `JupyterMCPConfig` pydantic model ([`jupyter_mcp_server/config.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/config.py)). Most map 1:1 to `jupyter-mcp-server` CLI options (kebab-case) and environment variables (upper snake-case).

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `transport` | str | `"stdio"` | The transport to use for the MCP server |
| `document_provider` | str | `"jupyter"` | Which backend holds the notebook documents: 'jupyter' or 'datalayer' |
| `code_sandbox_url` | str | `"http://localhost:8888"` | The code sandbox URL to use, or 'local' for direct serverapp access |
| `start_new_code_sandbox` | bool | `false` | Start a new code sandbox or use an existing one |
| `code_sandbox_id` | str \| None | `None` | The kernel ID to use |
| `code_sandbox_token` | str \| None | `None` | The code sandbox token to use for authentication |
| `code_sandbox_password` | str \| None | `None` | Password for Jupyter server authentication (alternative to token) |
| `sandbox_variant` | str | `"jupyter-server"` | Code execution sandbox variant. 'jupyter-server' (default) uses the code-sandboxes Jupyter Server engine. Any other value ('google-colab', 'kaggle', 'monty', 'modal', 'docker', 'eval', 'daytona', 'datalayer') routes execution through the code-sandboxes package. The spelling is not fussy: 'google_colab' and 'GOOGLE-COLAB' name the same variant. |
| `code_sandbox_proxy_token` | str \| None | `None` | Proxy token for the Google Colab sandbox variant (colab-runtime-proxy-token). |
| `code_sandbox_channels_url` | str \| None | `None` | For the 'google_colab'/'google-colab'/'colab' and 'kaggle' sandbox variants, the WebSocket channels URL of a running notebook session. When set, server_url and kernel_id are parsed from it. |
| `sandbox_environment` | str \| None | `None` | Environment name for cloud sandboxes (e.g. Datalayer/Modal). |
| `sandbox_gpu` | str \| None | `None` | GPU flavor / accelerator for sandbox engines that support it. Examples: Modal/Datalayer -> T4, A10G, A100, H100; Kaggle batch -> NvidiaTeslaT4, NvidiaTeslaP100 (aliases T4/P100). |
| `document_url` | str \| None | `None` | The document URL to use, or 'local' for direct serverapp access. Falls back to code_sandbox_url when unset. |
| `document_id` | str \| None | `None` | The document id to use. Optional - if omitted, can list and select notebooks interactively |
| `document_token` | str \| None | `None` | The document token to use for authentication |
| `document_password` | str \| None | `None` | Password for Jupyter document server authentication (alternative to token) |
| `port` | int | `4040` | The port to use for the Streamable HTTP transport |
| `jupyterlab` | bool | `true` | Enable JupyterLab mode (defaults to True) |
| `open_notebook_in_ui` | bool | `false` | Open the notebook in the JupyterLab UI when using it, which activates its tab (defaults to False) |
| `allowed_jupyter_mcp_tools` | str | `"notebook_run-all-cells,notebook_get-selected-cell"` | Comma-separated list of jupyter-mcp-tools to enable |
| `reconnect_interval` | int | `0` | Seconds to wait before reconnecting a dropped WebSocket connection to the kernel. 0 disables auto-reconnect. |
| `execution_timeout` | int | `120` | Default timeout in seconds for code execution. |
| `max_execution_timeout` | int | `3600` | Maximum allowed timeout in seconds for code execution. |

## Transports

The server speaks MCP over two transports, selected with `--transport` ([`jupyter_mcp_server/cli/commands/serve.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/cli/commands/serve.py)):

- `stdio` (default) — the server is spawned by the MCP client and framed over stdin/stdout.
- `streamable-http` — served by uvicorn on `--port`; requires `--mcp-token` unless `--insecure-mcp-noauth` is passed.

Both are started from [`jupyter_mcp_server/utils.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/utils.py).

## Serving modes

Beyond the standalone `MCP_SERVER` mode documented here, the package also runs embedded inside a Jupyter Server as an extension (`JUPYTER_SERVER` mode) — see [`jupyter_mcp_server/server_modes.py`](https://github.com/datalayer/jupyter-mcp-server/blob/main/jupyter_mcp_server/server_modes.py) and [`jupyter_mcp_server/jupyter_extension/`](https://github.com/datalayer/jupyter-mcp-server/tree/main/jupyter_mcp_server/jupyter_extension).

