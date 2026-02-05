# Jupyter MCP Server - MCPB Bundle

One-click installer for [Jupyter MCP Server](https://github.com/datalayer/jupyter-mcp-server) in Claude Desktop.

## What is this?

This directory contains the source files for building an MCPB (MCP Bundle) / DXT (Desktop Extension) package. The resulting `.mcpb` file allows users to install the Jupyter MCP Server in Claude Desktop with a single click — no terminal or manual configuration needed.

## Prerequisites

- [Node.js](https://nodejs.org/) (for the `mcpb` CLI tool)
- A running Jupyter server (JupyterLab or Jupyter Notebook) for the extension to connect to

## Building the Bundle

1. Install the MCPB CLI tool:

   ```bash
   npm install -g @anthropic-ai/mcpb
   ```

2. Build the `.mcpb` file from this directory:

   ```bash
   cd mcpb
   mcpb pack
   ```

   This creates `jupyter-mcp-server-0.22.1.mcpb` in the current directory.

## Installing in Claude Desktop

1. Double-click the `.mcpb` file, or drag it into Claude Desktop Settings
2. Claude Desktop will prompt you to configure:
   - **Jupyter Server URL**: The URL of your running Jupyter server (default: `http://localhost:8888`)
   - **Jupyter Server Token**: The authentication token for your Jupyter server
3. The extension is ready to use

## How It Works

This bundle uses the **UV runtime** type, which means:

- Claude Desktop automatically manages the Python environment
- Dependencies (`jupyter-mcp-server` and its transitive dependencies) are installed via `uv` into an isolated virtual environment
- No system-wide Python installation changes are made
- The server runs in **stdio** transport mode for direct communication with Claude Desktop

## Bundle Structure

```
mcpb/
├── manifest.json      # Extension metadata, tools, and user configuration
├── pyproject.toml     # Python dependencies for UV runtime
├── .mcpbignore        # Files to exclude from the bundle
├── README.md          # This file
└── src/
    └── server.py      # Thin entry point that launches the MCP server
```

## User Configuration

When installed, users provide two settings:

| Setting | Environment Variable | Description |
|---------|---------------------|-------------|
| Jupyter Server URL | `JUPYTER_URL` | URL of the Jupyter server (e.g., `http://localhost:8888`) |
| Jupyter Server Token | `JUPYTER_TOKEN` | Authentication token (stored securely in OS keychain) |

These are passed to the server as environment variables by Claude Desktop.
