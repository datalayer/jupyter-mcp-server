<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/datalayer-jupyter-mcp-server-badge.png)](https://mseep.ai/app/datalayer-jupyter-mcp-server)

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

**Jupyter MCP Server** is a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server implementation that provides interaction with 📓 Jupyter notebooks running in any JupyterLab (works also with your 💻 local JupyterLab).

## 🚀 Key Features

- ⚡ **Real-time control:** Instantly view notebook changes as they happen.
- 🔁 **Smart execution:** Automatically adjusts when a cell run fails thanks to cell output feedback.
- 🤝 **MCP-Compatible:** Works with any MCP client, such as Claude Desktop, Cursor, Windsurf, and more.

![Jupyter MCP Server Demo](https://assets.datalayer.tech/jupyter-mcp/jupyter-mcp-server-claude-demo.gif)

Explore our [Tools documentation](https://jupyter-mcp-server.datalayer.tech/docs/tools) to learn about the tools powering Jupyter MCP Server.

## 🏁 Getting Started

Follow our [Setup Guide](https://jupyter-mcp-server.datalayer.tech/docs/setup) or use the quick steps below:

### 1. Set Up Your Environment

```bash
pip install jupyterlab==4.4.1 jupyter-collaboration==4.0.2 ipykernel
pip uninstall -y pycrdt datalayer_pycrdt
pip install datalayer_pycrdt==0.12.17
```

### 2. Start JupyterLab

```bash
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
        "SERVER_URL",
        "-e",
        "TOKEN",
        "-e",
        "NOTEBOOK_PATH",
        "datalayer/jupyter-mcp-server:latest"
      ],
      "env": {
        "SERVER_URL": "http://host.docker.internal:8888",
        "TOKEN": "MY_TOKEN",
        "NOTEBOOK_PATH": "notebook.ipynb"
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
        "SERVER_URL",
        "-e",
        "TOKEN",
        "-e",
        "NOTEBOOK_PATH",
        "--network=host",
        "datalayer/jupyter-mcp-server:latest"
      ],
      "env": {
        "SERVER_URL": "http://localhost:8888",
        "TOKEN": "MY_TOKEN",
        "NOTEBOOK_PATH": "notebook.ipynb"
      }
    }
  }
}
```

For detailed instructions on configuring various MCP clients—including [Claude Desktop](https://jupyter-mcp-server.datalayer.tech/docs/clients/claude_desktop), [Cursor](https://jupyter-mcp-server.datalayer.tech/docs/clients/cursor), [Cline](https://jupyter-mcp-server.datalayer.tech/docs/clients/cline), and [Windsurf](https://jupyter-mcp-server.datalayer.tech/docs/clients/windsurf)—see the [Clients documentation](https://jupyter-mcp-server.datalayer.tech/docs/clients).

## 📚 Resources

Looking for blog posts, videos, or other materials about Jupyter MCP Server?<br>
👉 Visit the [Resources section](https://jupyter-mcp-server.datalayer.tech/docs/resources) for more.
