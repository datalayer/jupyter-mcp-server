<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://images.datalayer.io/brand/logos/datalayer-horizontal.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

# Jupyter MCP Server CLI Example

This example demonstrates a local end-to-end setup with:

1. JupyterLab on `http://127.0.0.1:8888`
1. Jupyter MCP Server (Streamable HTTP) on `http://127.0.0.1:4040/mcp`
1. A pydantic-ai interactive CLI connected to the Jupyter MCP Server

The `start` target launches everything in one command.

For local-only testing, `start-noauth` runs MCP with `--insecure-mcp-noauth`.

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Pydantic AI Interactive CLI                │
│                      (examples/cli/agent.py)                │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP + Authorization header
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               Jupyter MCP Server (streamable-http)          │
│                   http://127.0.0.1:4040/mcp                 │
└──────────────────────────────┬──────────────────────────────┘
                               │ Jupyter API
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                           JupyterLab                        │
│                   http://127.0.0.1:8888/lab                 │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install dependencies

```bash
make install
```

### 2. Run everything

```bash
make start
```

Or run without MCP endpoint authentication (local dev only):

```bash
make start-noauth
```

If JupyterLab and MCP are already running in no-auth mode, run only the CLI:

```bash
make start-noauth-agent
```

This will:

1. Ask for an optional sandbox variant (`none`, `jupyterhub`, `datalayer`, `daytona`, `e2b`, `coreweave`, `cloudflare`, `google-colab`, `kaggle`, `monty`, `modal`, `eval`, `docker`)
1. Start JupyterLab with token auth
1. Wait until JupyterLab is ready
1. Start Jupyter MCP Server with Streamable HTTP transport
1. Wait for MCP health endpoint
1. Launch the pydantic-ai interactive CLI

If you choose `none` (or press Enter), code execution uses standard Jupyter kernels.
If you choose a concrete sandbox backend, make sure the `jupyter_mcp_sandboxes`
extension is installed (`pip install jupyter_mcp_sandboxes`).

Press `Ctrl+C` to stop the CLI and both background servers.

Security note: `start-noauth` disables MCP client authentication and should not be used outside local development.

## Configuration

You can override settings at runtime:

```bash
MCP_TOKEN=my-mcp-token \
JUPYTER_TOKEN=my-jupyter-token \
MODEL=bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
make start
```

To skip the interactive prompt (useful for scripts/CI), set `SANDBOX_VARIANT`:

```bash
SANDBOX_VARIANT=none make start
```

Use a concrete sandbox backend when needed:

```bash
SANDBOX_VARIANT=monty make start
```

Variant-specific required environment variables:

- `jupyter-server` / `eval` / `docker` / `monty`: no extra variables required.
- `jupyterhub`: requires `CODE_SANDBOX_URL` and `CODE_SANDBOX_TOKEN`.
- `datalayer`: requires `CODE_SANDBOX_URL` and `CODE_SANDBOX_TOKEN`.
- `google-colab`: requires either `CODE_SANDBOX_CHANNELS_URL`, or `CODE_SANDBOX_URL` + `CODE_SANDBOX_ID` + `CODE_SANDBOX_PROXY_TOKEN`.
- `kaggle`: defaults to batch mode (for example `KAGGLE_API_TOKEN` or Kaggle credentials). For interactive mode, set `CODE_SANDBOX_URL` and either `KAGGLE_API_TOKEN`/`CODE_SANDBOX_TOKEN` (create a new kernel) or `CODE_SANDBOX_ID`/`CODE_SANDBOX_CHANNELS_URL` (connect existing kernel). Optional accelerator: `SANDBOX_GPU` (for example `T4`, `P100`, `NvidiaTeslaT4`).
- `modal`: requires either (`MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET`) or a local
  Modal login in `~/.modal.toml` (for example after `modal token new`).
- `daytona`: requires `DAYTONA_API_KEY`, or `DAYTONA_JWT_TOKEN` +
  `DAYTONA_ORGANIZATION_ID`. Optional accelerator: `SANDBOX_GPU` (for example `H100`).
- `e2b`: requires `E2B_API_KEY`. Optional: `E2B_DOMAIN`.
- `coreweave`: requires `CWSANDBOX_API_KEY`. Optional: `CWSANDBOX_BASE_URL`, and
  `SANDBOX_GPU` (for example `H100`) to run on a GPU.
- `cloudflare`: requires `CLOUDFLARE_SANDBOX_API_URL` and
  `CLOUDFLARE_SANDBOX_API_KEY`, the URL and key of a deployed sandbox bridge Worker.

For the variants the targets know how to check — `jupyterhub`, `datalayer`,
`google-colab`, `kaggle` and `modal` — `make start` and `make start-noauth`
validate these requirements before launching the MCP server and print a clear
error with an example command if anything is missing.

Supported variables:

- `MODEL` (default: `bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- `JUPYTER_PORT` (default: `8888`)
- `MCP_PORT` (default: `4040`)
- `JUPYTER_TOKEN` (default: `MY_TOKEN`)
- `MCP_TOKEN` (default: `MY_MCP_TOKEN`)
- `DOCUMENT_ID` (default: `notebook.ipynb`)
- `SANDBOX_VARIANT` (optional; when unset, `make start` prompts and defaults to `none` = Jupyter kernels)
- `CODE_SANDBOX_URL`, `CODE_SANDBOX_TOKEN`, `CODE_SANDBOX_ID`, `CODE_SANDBOX_PROXY_TOKEN`, `CODE_SANDBOX_CHANNELS_URL`, `KAGGLE_API_TOKEN`, `SANDBOX_GPU` (required for some variants)
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` (required for Modal unless `~/.modal.toml` exists)
- `DAYTONA_API_KEY`, or `DAYTONA_JWT_TOKEN` + `DAYTONA_ORGANIZATION_ID` (required for Daytona)
- `E2B_API_KEY`, `E2B_DOMAIN` (required for E2B; the domain is optional)
- `CWSANDBOX_API_KEY`, `CWSANDBOX_BASE_URL` (required for CoreWeave; the base URL is optional)
- `CLOUDFLARE_SANDBOX_API_URL`, `CLOUDFLARE_SANDBOX_API_KEY` (both required for Cloudflare)

The CLI targets export Bedrock credentials from these environment variables:

- `DATALAYER_BEDROCK_AWS_ACCESS_KEY_ID`
- `DATALAYER_BEDROCK_AWS_SECRET_ACCESS_KEY`
- `DATALAYER_BEDROCK_AWS_DEFAULT_REGION`

## Files

- `Makefile`: installs dependencies and orchestrates startup
- `agent.py`: pydantic-ai CLI connected to Jupyter MCP Server via `MCPToolset`

## Useful Commands

```bash
make help
make start
make start-noauth
make start-noauth-agent
make clean
```
