<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://assets.datalayer.tech/datalayer-25.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)
<div align="center">

<!-- omit in toc -->

# 🪐✨ Jupyter MCP Server

<strong>An [MCP](https://modelcontextprotocol.io) service specifically developed for AI to connect and manage Jupyter Notebooks in real-time</strong>

*Developed by [Datalayer](https://github.com/datalayer)*

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-mcp-server)](https://pypi.org/project/jupyter-mcp-server)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker Pulls](https://img.shields.io/docker/pulls/datalayer/jupyter-mcp-server)](https://hub.docker.com/r/datalayer/jupyter-mcp-server)
[![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)


[![MseeP.ai Security Assessment](https://img.shields.io/static/v1?label=MseeP.ai&message=4.3&logo=MseeP.ai&style=flat&color=1ABC9C)](https://mseep.ai/app/datalayer-jupyter-mcp-server)
[![Trust Score](https://archestra.ai/mcp-catalog/api/badge/quality/datalayer/jupyter-mcp-server)](https://archestra.ai/mcp-catalog/datalayer__jupyter-mcp-server)


> 🚨 **NEW IN 0.14.0:** Multi-notebook support! You can now seamlessly switch between multiple notebooks in a single session. [Read more in the release notes.](https://jupyter-mcp-server.datalayer.tech/releases)

![Jupyter MCP Server Demo](https://assets.datalayer.tech/jupyter-mcp/mcp-demo-multimodal.gif)

</div>

## 📖 Table of Contents
- [Key Features](#-key-features)
- [Getting Started](#-getting-started)
  - [Set Up Your Environment](#1-set-up-your-environment)
  - [Start JupyterLab](#2-start-jupyterlab)
  - [Configure Your Preferred MCP Client](#3-configure-your-preferred-mcp-client)
- [Contributing](#-contributing)
- [Resources](#-resources)


## 🚀 Key Features

- ⚡ **Real-time control:** Instantly view notebook changes as they happen.
- 🔁 **Smart execution:** Automatically adjusts when a cell run fails thanks to cell output feedback.
- 🧠 **Context-aware:** Understands the entire notebook context for more relevant interactions.
- 📊 **Multimodal support:** Support different output types, including images, plots, and text.
- 📚 **Multi-notebook support:** Seamlessly switch between multiple notebooks.
- 🤝 **MCP-compatible:** Works with any MCP client, such as Claude Desktop, Cursor, Windsurf, and more.

Compatible with any Jupyter deployment (local, JupyterHub, ...) and with [Datalayer](https://datalayer.ai/) hosted Notebooks.

🛠️ This MCP offers multiple tools such as `insert_cell`, `execute_cell`, `list_files`, `read_cell`, and more, enabling advanced interactions with Jupyter notebooks. Explore our [tools documentation](https://jupyter-mcp-server.datalayer.tech/tools) to learn about all the tools powering Jupyter MCP Server.

## 🏁 Getting Started

For comprehensive setup instructions—including `Streamable HTTP` transport, running as a Jupyter Server extension and advanced configuration—check out [our documentation](https://jupyter-mcp-server.datalayer.tech/). Or, get started quickly with `JupyterLab` and `STDIO` transport here below.

### 1. Set Up Your Environment

```bash
pip install jupyterlab==4.4.1 jupyter-collaboration==4.0.2 ipykernel
pip uninstall -y pycrdt datalayer_pycrdt
pip install datalayer_pycrdt==0.12.17
```

### 2. Start JupyterLab

```bash
# Start JupyterLab on port 8888, allowing access from any IP and setting a token
jupyter lab --port 8888 --IdentityProvider.token MY_TOKEN --ip 0.0.0.0
```

> [!NOTE]
> If you are running notebooks through JupyterHub instead of JupyterLab as above, you should:
>
> - Set the environment variable `JUPYTERHUB_ALLOW_TOKEN_IN_URL=1` in the single-user environment.
> - Ensure your API token (`MY_TOKEN`) is created with `access:servers` scope in the Hub.

### 3. Configure Your Preferred MCP Client

You can choose between two deployment methods: **uvx** (lightweight and faster, recommended for first try) or **Docker** (recommended for production).

<details>
<summary><b>📦 Using uvx (Quick Start)</b></summary>

First, install `uv`:
```bash
pip install uv
uv --version
# should be 0.6.14 or higher
```
See more details on [uv installation](https://docs.astral.sh/uv/getting-started/installation/).

Then, configure your client:
```json
{
  "mcpServers": {
    "jupyter": {
      "command": "uvx",
      "args": ["jupyter-mcp-server"],
      "env": {
        "DOCUMENT_URL": "http://localhost:8888",
        "DOCUMENT_TOKEN": "MY_TOKEN",
        "DOCUMENT_ID": "notebook.ipynb",
        "RUNTIME_URL": "http://localhost:8888",
        "RUNTIME_TOKEN": "MY_TOKEN",
        "ALLOW_IMG_OUTPUT": "true"
      }
    }
  }
}
```

</details>

<details>
<summary><b>🐳 Using Docker (Production)</b></summary>

**On macOS and Windows:**
```json
{
  "mcpServers": {
    "jupyter": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "DOCUMENT_URL",
        "-e", "DOCUMENT_TOKEN",
        "-e", "DOCUMENT_ID",
        "-e", "RUNTIME_URL",
        "-e", "RUNTIME_TOKEN",
        "-e", "ALLOW_IMG_OUTPUT",
        "datalayer/jupyter-mcp-server:latest"
      ],
      "env": {
        "DOCUMENT_URL": "http://host.docker.internal:8888",
        "DOCUMENT_TOKEN": "MY_TOKEN",
        "DOCUMENT_ID": "notebook.ipynb",
        "RUNTIME_URL": "http://host.docker.internal:8888",
        "RUNTIME_TOKEN": "MY_TOKEN",
        "ALLOW_IMG_OUTPUT": "true"
      }
    }
  }
}
```

**On Linux:**
```json
{
  "mcpServers": {
    "jupyter": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "DOCUMENT_URL",
        "-e", "DOCUMENT_TOKEN",
        "-e", "DOCUMENT_ID",
        "-e", "RUNTIME_URL",
        "-e", "RUNTIME_TOKEN",
        "-e", "ALLOW_IMG_OUTPUT",
        "--network=host",
        "datalayer/jupyter-mcp-server:latest"
      ],
      "env": {
        "DOCUMENT_URL": "http://localhost:8888",
        "DOCUMENT_TOKEN": "MY_TOKEN",
        "DOCUMENT_ID": "notebook.ipynb",
        "RUNTIME_URL": "http://localhost:8888",
        "RUNTIME_TOKEN": "MY_TOKEN",
        "ALLOW_IMG_OUTPUT": "true"
      }
    }
  }
}
```

</details>

> [!TIP]
> 1. Ensure the `port` of the `DOCUMENT_URL` and `RUNTIME_URL` match those used in the `jupyter lab` command.
> 2. In a basic setup, `DOCUMENT_URL` and `RUNTIME_URL` are the same. `DOCUMENT_TOKEN`, and `RUNTIME_TOKEN` are also the same and is actually the Jupyter Token.
> 3. The `DOCUMENT_ID` parameter specifies the path to the notebook you want to connect to. It should be relative to the directory where JupyterLab was started.
>    - **Optional:** If you omit `DOCUMENT_ID`, the MCP client can automatically list all available notebooks on the Jupyter server, allowing you to select one interactively via your prompts.
>    - **Flexible:** Even if you set `DOCUMENT_ID`, the MCP client can still browse, list, switch to, or even create new notebooks at any time.

For detailed instructions on configuring various MCP clients—including [Claude Desktop](https://jupyter-mcp-server.datalayer.tech/clients/claude_desktop), [VS Code](https://jupyter-mcp-server.datalayer.tech/clients/vscode), [Cursor](https://jupyter-mcp-server.datalayer.tech/clients/cursor), [Cline](https://jupyter-mcp-server.datalayer.tech/clients/cline), and [Windsurf](https://jupyter-mcp-server.datalayer.tech/clients/windsurf) — see the [Clients documentation](https://jupyter-mcp-server.datalayer.tech/clients).

## 🤝 Contributing

We welcome contributions of all kinds! Here are some examples:

- 🐛 Bug fixes
- 📝 Improvements to existing features
- ✨ New feature development
- 📚 Documentation improvements

For detailed instructions on how to get started with development and submit your contributions, please see our [**Contributing Guide**](CONTRIBUTING.md).

### Our Contributors

<a href="https://github.com/datalayer/jupyter-mcp-server/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=datalayer/jupyter-mcp-server" />
</a>

## 📚 Resources

Looking for blog posts, videos, or other materials about Jupyter MCP Server?

👉 Visit the [**Resources section**](https://jupyter-mcp-server.datalayer.tech/resources) in our documentation for more!

## ⭐ Star History

<a href="https://star-history.com/#/repos/datalayer/jupyter-mcp-server&type=Date">
  <img src="https://api.star-history.com/svg?repos=datalayer/jupyter-mcp-server&type=Date" alt="Star History Chart">
</a>

---

<div align="center">

**If this project is helpful to you, please give us a ⭐️**

Made with ❤️ by [Datalayer](https://github.com/datalayer)

</div>