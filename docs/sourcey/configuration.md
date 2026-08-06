---
title: "Configuration"
description: "Every setting of JupyterMCPConfig, generated from the pydantic model at the pinned commit."
---

# Configuration

All runtime settings live on the `JupyterMCPConfig` pydantic model ([`jupyter_mcp_server/config.py`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/config.py)). Most map 1:1 to `jupyter-mcp-server` CLI options (kebab-case) and environment variables (upper snake-case).

| Setting | Type | Default | Description |
| --- | --- | --- | --- |
| `transport` | str | `"stdio"` | The transport to use for the MCP server |
| `provider` | str | `"jupyter"` | The provider to use for the document and code sandbox |
| `code_sandbox_url` | str | `"http://localhost:8888"` | The code sandbox URL to use, or 'local' for direct serverapp access |
| `start_new_code_sandbox` | bool | `false` | Start a new code sandbox or use an existing one |
| `code_sandbox_id` | str \| None | `None` | The kernel ID to use |
| `code_sandbox_token` | str \| None | `None` | The code sandbox token to use for authentication |
| `code_sandbox_password` | str \| None | `None` | Password for Jupyter server authentication (alternative to token) |
| `sandbox_variant` | str | `"jupyter"` | Code execution sandbox variant. 'jupyter' (default) uses the code-sandboxes Jupyter engine. Any other value ('colab', 'kaggle', 'monty', 'modal', 'docker', 'eval', 'datalayer') routes execution through the code-sandboxes package. |
| `code_sandbox_proxy_token` | str \| None | `None` | Proxy token for the Colab sandbox variant (colab-code-sandbox-proxy-token). |
| `code_sandbox_channels_url` | str \| None | `None` | For the 'colab' and 'kaggle' sandbox variants, the WebSocket channels URL of a running notebook session. When set, server_url and kernel_id are parsed from it. |
| `sandbox_environment` | str \| None | `None` | Environment name for cloud sandboxes (e.g. Datalayer/Modal). |
| `sandbox_gpu` | str \| None | `None` | GPU flavor / accelerator for sandbox engines that support it. Examples: Modal/Datalayer -> T4, A10G, A100, H100; Kaggle batch -> NvidiaTeslaT4, NvidiaTeslaP100 (aliases T4/P100). |
| `document_url` | str | `"http://localhost:8888"` | The document URL to use, or 'local' for direct serverapp access |
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

The server speaks MCP over two transports, selected with `--transport` ([`jupyter_mcp_server/cli/commands/serve.py:20`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/cli/commands/serve.py#L20)):

- `stdio` (default) — the server is spawned by the MCP client and framed over stdin/stdout ([`jupyter_mcp_server/utils.py:345`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/utils.py#L345)).
- `streamable-http` — served by uvicorn on `--port`; requires `--mcp-token` unless `--insecure-mcp-noauth` is passed ([`jupyter_mcp_server/utils.py:253`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/utils.py#L253)).

## Serving modes

Beyond the standalone `MCP_SERVER` mode documented here, the package also runs embedded inside a Jupyter Server as an extension (`JUPYTER_SERVER` mode) — see [`jupyter_mcp_server/server_modes.py`](https://github.com/datalayer/jupyter-mcp-server/blob/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/server_modes.py) and [`jupyter_mcp_server/jupyter_extension/`](https://github.com/datalayer/jupyter-mcp-server/tree/c132b061240dbe53d83290bff3007f43fc01ea6b/jupyter_mcp_server/jupyter_extension).

