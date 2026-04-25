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
2. Jupyter MCP Server (Streamable HTTP) on `http://127.0.0.1:4040/mcp`
3. A pydantic-ai interactive CLI connected to the Jupyter MCP Server

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

1. Start JupyterLab with token auth
2. Wait until JupyterLab is ready
3. Start Jupyter MCP Server with Streamable HTTP transport
4. Wait for MCP health endpoint
5. Launch the pydantic-ai interactive CLI

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

Supported variables:

- `MODEL` (default: `bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- `JUPYTER_PORT` (default: `8888`)
- `MCP_PORT` (default: `4040`)
- `JUPYTER_TOKEN` (default: `MY_TOKEN`)
- `MCP_TOKEN` (default: `MY_MCP_TOKEN`)
- `DOCUMENT_ID` (default: `notebook.ipynb`)

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
