<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://images.datalayer.io/brand/logos/datalayer-horizontal.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

<div align="center">

<!-- omit in toc -->

# 🪐🔧 Jupyter MCP Server Sandboxes Extension

</div>

`jupyter_mcp_sandboxes` is an optional extension for
[jupyter-mcp-server](https://github.com/datalayer/jupyter-mcp-server) that adds
sandbox-backed code execution. It is discovered automatically through the
`jupyter_mcp_server.extensions` entry point (powered by
[`reactor`](https://github.com/datalayer/reactor)) once installed.

## Features

Installing this extension exposes four additional MCP tools:

- `launch_sandbox` — launch a sandbox runtime (`eval`, `docker`, `jupyter`,
  `datalayer`, `colab`, `kaggle`, `monty`, `modal`).
- `list_sandboxes` — list launched sandboxes and their state.
- `use_sandbox` — select (or clear) the active sandbox used by `execute_code`.
- `terminate_sandbox` — stop and unregister a sandbox.

It also lets `SANDBOX_VARIANT` route the standard notebook/cell execution tools
through a non-`jupyter` backend via a `SandboxKernel` adapter.

## Installation

```bash
pip install jupyter_mcp_sandboxes
```

Backend-specific extras are provided by the underlying
[`code-sandboxes`](https://github.com/datalayer/code-sandboxes) package, e.g.:

```bash
pip install "code-sandboxes[modal]"   # Modal
pip install "code-sandboxes[colab]"   # Google Colab
pip install "code-sandboxes[kaggle]"  # Kaggle
```

## Usage

Once installed, start `jupyter-mcp-server` as usual — no flag is required. The
sandbox tools appear automatically. To route `execute_code` through a specific
backend by default, set `SANDBOX_VARIANT`:

```bash
SANDBOX_VARIANT=monty jupyter-mcp-server start --transport streamable-http
```

## License

BSD 3-Clause License. Copyright (c) 2024- Datalayer, Inc.
