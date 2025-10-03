<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://assets.datalayer.tech/datalayer-25.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

# 🪐✨ Jupyter MCP Server

[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-mcp-server)](https://pypi.org/project/jupyter-mcp-server)
<a href="https://mseep.ai/app/datalayer-jupyter-mcp-server">
<img src="https://mseep.net/pr/datalayer-jupyter-mcp-server-badge.png" alt="MseeP.ai Security Assessment Badge" width="100" />
</a>

[![Trust Score](https://archestra.ai/mcp-catalog/api/badge/quality/datalayer/jupyter-mcp-server)](https://archestra.ai/mcp-catalog/datalayer__jupyter-mcp-server)

> 🚨 **BREAKING CHANGE** For version `0.11.0+`, `room` has been renamed to `document`. [Read more in the release notes.](https://jupyter-mcp-server.datalayer.tech/releases)

**Jupyter MCP Server** is a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server implementation that enables **real-time** interaction with 📓 Jupyter Notebooks, allowing AI to edit, document and execute code for data analysis, visualization etc.

Compatible with any Jupyter deployment (local, JupyterHub, ...) and with [Datalayer](https://datalayer.ai/) hosted Notebooks.

## 🚀 Key Features

- ⚡ **Real-time control:** Instantly view notebook changes as they happen.
- 🔁 **Smart execution:** Automatically adjusts when a cell run fails thanks to cell output feedback.
- 🧠 **Context-aware:** Understands the entire notebook context for more relevant interactions.
- 📊 **Multimodal support:** Support different output types, including images, plots, and text.
- 📁 **Multi-notebook support:** Seamlessly switch between multiple notebooks.
- 🤝 **MCP-compatible:** Works with any MCP client, such as Claude Desktop, Cursor, Windsurf, and more.

![Jupyter MCP Server Demo](https://assets.datalayer.tech/jupyter-mcp/mcp-demo-multimodal.gif)

🛠️ This MCP offers multiple tools such as `insert_cell`, `execute_cell`, `list_all_files`, `read_cell`, and more, enabling advanced interactions with Jupyter notebooks. Explore our [tools documentation](https://jupyter-mcp-server.datalayer.tech/tools) to learn about all the tools powering Jupyter MCP Server.

## 🏁 Getting Started

For comprehensive setup instructions—including `Streamable HTTP` transport and advanced configuration—check out [our documentation](https://jupyter-mcp-server.datalayer.tech/). Or, get started quickly with `JupyterLab` and `stdio` transport here below.

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

> [!NOTE]
> If you are running notebooks through JupyterHub instead of JupyterLab as above, you should:
>
> - Set the environment variable `JUPYTERHUB_ALLOW_TOKEN_IN_URL=1` in the single-user environment.
> - Ensure your API token (`MY_TOKEN`) is created with `access:servers` scope in the Hub.


### 3. Configure Your Preferred MCP Client

> [!TIP]
>
> 1. Ensure the `port` of the `DOCUMENT_URL` and `RUNTIME_URL` match those used in the `jupyter lab` command.
>
> 2. In a basic setup, `DOCUMENT_URL` and `RUNTIME_URL` are the same. `DOCUMENT_TOKEN`, and `RUNTIME_TOKEN` are also the same and is actually the Jupyter Token.
>
> 3. The `DOCUMENT_ID` parameter specifies the path to the notebook you want to connect to. It should be relative to the directory where JupyterLab was started.  
> 
> - **Optional:** If you omit `DOCUMENT_ID`, the MCP client can automatically list all available notebooks on the Jupyter server, allowing you to select one interactively via your prompts.
> - **Flexible:** Even if you set `DOCUMENT_ID`, the MCP client can still browse, list, switch to, or even create new notebooks at any time.
> 

#### MacOS and Windows

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

#### Linux

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

For detailed instructions on configuring various MCP clients—including [Claude Desktop](https://jupyter-mcp-server.datalayer.tech/clients/claude_desktop), [VS Code](https://jupyter-mcp-server.datalayer.tech/clients/vscode), [Cursor](https://jupyter-mcp-server.datalayer.tech/clients/cursor), [Cline](https://jupyter-mcp-server.datalayer.tech/clients/cline), and [Windsurf](https://jupyter-mcp-server.datalayer.tech/clients/windsurf) — see the [Clients documentation](https://jupyter-mcp-server.datalayer.tech/clients).

## 📚 Resources

Looking for blog posts, videos, or other materials about Jupyter MCP Server?

👉 Visit the [Resources section](https://jupyter-mcp-server.datalayer.tech/resources).
