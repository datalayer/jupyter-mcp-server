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

1. Ask for an optional sandbox variant (`none`, `jupyterhub`, `datalayer`, `colab`, `monty`, `modal`, `eval`, `docker`)
1. Start JupyterLab with token auth
1. Wait until JupyterLab is ready
1. Start Jupyter MCP Server with Streamable HTTP transport
1. Wait for MCP health endpoint
1. Launch the pydantic-ai interactive CLI

If you choose `none` (or press Enter), code execution uses standard Jupyter kernels.

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

- `jupyter` / `eval` / `docker` / `monty`: no extra variables required.
- `jupyterhub`: requires `RUNTIME_URL` and `RUNTIME_TOKEN`.
- `datalayer`: requires `RUNTIME_URL` and `RUNTIME_TOKEN`.
- `colab`: requires `RUNTIME_URL`, `RUNTIME_ID`, and `RUNTIME_PROXY_TOKEN`.
- `modal`: requires either (`MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET`) or a local
  Modal login in `~/.modal.toml` (for example after `modal token new`).

The `make start` and `make start-noauth` targets validate these requirements
before launching the MCP server and print a clear error with an example command
if anything is missing.

Supported variables:

- `MODEL` (default: `bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- `JUPYTER_PORT` (default: `8888`)
- `MCP_PORT` (default: `4040`)
- `JUPYTER_TOKEN` (default: `MY_TOKEN`)
- `MCP_TOKEN` (default: `MY_MCP_TOKEN`)
- `DOCUMENT_ID` (default: `notebook.ipynb`)
- `SANDBOX_VARIANT` (optional; when unset, `make start` prompts and defaults to `none` = Jupyter kernels)
- `RUNTIME_URL`, `RUNTIME_TOKEN`, `RUNTIME_ID`, `RUNTIME_PROXY_TOKEN` (required for some variants)
- `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` (required for Modal unless `~/.modal.toml` exists)

The CLI targets export Bedrock credentials from these environment variables:

- `DATALAYER_BEDROCK_AWS_ACCESS_KEY_ID`
- `DATALAYER_BEDROCK_AWS_SECRET_ACCESS_KEY`
- `DATALAYER_BEDROCK_AWS_DEFAULT_REGION`

## Files

- `Makefile`: installs dependencies and orchestrates startup
- `agent.py`: pydantic-ai CLI connected to Jupyter MCP Server via `MCPServerStreamableHTTP`

## Useful Commands

```bash
make help
make start
make start-noauth
make start-noauth-agent
make clean
```
