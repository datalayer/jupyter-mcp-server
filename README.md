<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://assets.datalayer.tech/datalayer-25.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

# 🪐 ✨ Jupyter MCP Server

[![Github Actions Status](https://github.com/datalayer/jupyter-mcp-server/workflows/Build/badge.svg)](https://github.com/datalayer/jupyter-mcp-server/actions/workflows/build.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/jupyter-mcp-server)](https://pypi.org/project/jupyter-mcp-server)
[![smithery badge](https://smithery.ai/badge/@datalayer/jupyter-mcp-server)](https://smithery.ai/server/@datalayer/jupyter-mcp-server)

Jupyter MCP Server is a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server implementation that provides interaction with 📓 Jupyter notebooks running in any JupyterLab (works also with your 💻 local JupyterLab).

![Jupyter MCP Server](https://assets.datalayer.tech/jupyter-mcp/jupyter-mcp-server-claude-demo.gif)

## Start JupyterLab

Make sure you have the following installed. The collaboration package is needed as the modifications made on the notebook can be seen thanks to [Jupyter Real Time Collaboration](https://jupyterlab.readthedocs.io/en/stable/user/rtc.html).

```bash
pip install jupyterlab jupyter-collaboration ipykernel
pip uninstall -y pycrdt datalayer_pycrdt
pip install datalayer_pycrdt
```

Then, start JupyterLab with the following command.

```bash
jupyter lab --port 8888 --IdentityProvider.token MY_TOKEN --ip 0.0.0.0
```

You can also run `make jupyterlab`.

> [!NOTE]
>
> The `--ip` is set to `0.0.0.0` to allow the MCP server running in a Docker container to access your local JupyterLab.

## Use with Claude Desktop

Claude Desktop can be downloaded [from this page](https://claude.ai/download) for macOS and Windows.

For Linux, we had success using this [UNOFFICIAL build script based on nix](https://github.com/k3d3/claude-desktop-linux-flake)

```bash
# ⚠️ UNOFFICIAL
# You can also run `make claude-linux`
NIXPKGS_ALLOW_UNFREE=1 nix run github:k3d3/claude-desktop-linux-flake \
  --impure \
  --extra-experimental-features flakes \
  --extra-experimental-features nix-command
```

To use this with Claude Desktop, add the following to your `claude_desktop_config.json` (read more on the [MCP documentation website](https://modelcontextprotocol.io/quickstart/user#2-add-the-filesystem-mcp-server)).

> [!IMPORTANT]
>
> Ensure the port of the `SERVER_URL`and `TOKEN` match those used in the `jupyter lab` command.
>
> The `NOTEBOOK_PATH` should be relative to the directory where JupyterLab was started.

### Claude Configuration on macOS and Windows

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

### Claude Configuration on Linux

```bash
CLAUDE_CONFIG=${HOME}/.config/Claude/claude_desktop_config.json
cat <<EOF > $CLAUDE_CONFIG
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
EOF
cat $CLAUDE_CONFIG
```

## Components

### Tools

The server currently offers 3 tools:

1. `add_execute_code_cell`

- Add and execute a code cell in a Jupyter notebook.
- Input:
  - `cell_content`(string): Code to be executed.
- Returns: Cell output.

2. `add_markdown_cell`

- Add a markdown cell in a Jupyter notebook.
- Input:
  - `cell_content`(string): Markdown content.
- Returns: Success message.

3. `download_earth_data_granules`

   ⚠️ We plan to migrate this tool to a separate repository in the future as it is specific to Geospatial analysis.

- Add a code cell in a Jupyter notebook to download Earth data granules from NASA Earth Data.
- Input:
  - `folder_name`(string): Local folder name to save the data.
  - `short_name`(string): Short name of the Earth dataset to download.
  - `count`(int): Number of data granules to download.
  - `temporal` (tuple): (Optional) Temporal range in the format (date_from, date_to).
  - `bounding_box` (tuple): (Optional) Bounding box in the format (lower_left_lon, lower_left_lat, upper_right_lon, upper_right_lat).
- Returns: Cell output.

## Building

You can build the Docker image it from source.

```bash
make build-docker
```

## Installing via Smithery

To install Jupyter MCP Server for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@datalayer/jupyter-mcp-server):

```bash
npx -y @smithery/cli install @datalayer/jupyter-mcp-server --client claude
```
