<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://assets.datalayer.tech/datalayer-25.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

# 🪐✨ Jupyter MCP Server

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-mcp-server)](https://pypi.org/project/jupyter-mcp-server)
[![smithery badge](https://smithery.ai/badge/@datalayer/jupyter-mcp-server)](https://smithery.ai/server/@datalayer/jupyter-mcp-server)

**Jupyter MCP Server** is a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server implementation that provides interaction with 📓 Jupyter notebooks running in any JupyterLab or Notebook>=7.

This works also with your 💻 local Jupyter.

## 🚀 Key Features

- ⚡ **Real-time control:** Instantly view notebook changes as they happen.
- 🔁 **Smart execution:** Automatically adjusts when a cell run fails thanks to cell output feedback.
- 🤝 **MCP-Compatible:** Works with any MCP client, such as Claude Desktop, Cursor, Windsurf, and more.

![Jupyter MCP Server Demo](https://assets.datalayer.tech/jupyter-mcp/jupyter-mcp-server-claude-demo.gif)

🛠️ This MCP offers multiple tools such as `insert_execute_code_cell`, `append_markdown_cell`, `get_notebook_info`, `read_cell`, and more, enabling advanced interactions with Jupyter notebooks. Explore our [documentation](https://jupyter-mcp-server.datalayer.tech/tools) to learn about all the tools powering Jupyter MCP Server.

## 🏁 Getting Started

For comprehensive setup instructions—including `Streamable HTTP` transport and advanced configuration—see our [Setup Guide](https://jupyter-mcp-server.datalayer.tech/setup). Or, get started quickly with the `stdio` transport here below.

### 1. Set Up Your Environment

```bash
pip install jupyterlab==4.4.1 jupyter-collaboration==4.0.2 ipykernel
pip uninstall -y pycrdt datalayer_pycrdt
pip install datalayer_pycrdt==0.12.17
```

### 2. Start JupyterLab

```bash
# make jupyterlab
jupyter lab --port 8888 --IdentityProvider.token MY_TOKEN --ip 0.0.0.0
```

### 3. Configure Your Preferred MCP Client

#### MacOS and Windows

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "ROOM_URL",
        "-e",
        "RUNTIME_TOKEN",
        "-e",
        "ROOM_ID",
        "datalayer/jupyter-mcp-server:latest"
      ],
      "env": {
        "ROOM_URL": "http://host.docker.internal:8888",
        "RUNTIME_TOKEN": "MY_TOKEN",
        "ROOM_ID": "notebook.ipynb"
      }
    }
  }
}
```

#### Linux

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "ROOM_URL",
        "-e",
        "RUNTIME_TOKEN",
        "-e",
        "ROOM_ID",
        "--network=host",
        "datalayer/jupyter-mcp-server:latest"
      ],
      "env": {
        "ROOM_URL": "http://localhost:8888",
        "RUNTIME_TOKEN": "MY_TOKEN",
        "ROOM_ID": "notebook.ipynb"
      }
    }
  }
}
```

For detailed instructions on configuring various MCP clients—including [Claude Desktop](https://jupyter-mcp-server.datalayer.tech/clients/claude_desktop), [VS Code](https://jupyter-mcp-server.datalayer.tech/clients/vscode), [Cursor](https://jupyter-mcp-server.datalayer.tech/clients/cursor), [Cline](https://jupyter-mcp-server.datalayer.tech/clients/cline), and [Windsurf](https://jupyter-mcp-server.datalayer.tech/clients/windsurf) — see the [Clients documentation](https://jupyter-mcp-server.datalayer.tech/clients).

## 📚 Resources

Looking for blog posts, videos, or other materials about Jupyter MCP Server?

👉 Visit the [Resources section](https://jupyter-mcp-server.datalayer.tech/resources).
