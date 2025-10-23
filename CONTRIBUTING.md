<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Contributing to Jupyter MCP Server

First off, thank you for considering contributing to Jupyter MCP Server! It's people like you that make this project great. Your contributions help us improve the project and make it more useful for everyone!

## Code of Conduct

This project and everyone participating in it is governed by the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior.

## How Can I Contribute?

We welcome contributions of all kinds, including:
- 🐛 Bug fixes
- 📝 Improvements to existing features or documentation
- ✨ New feature development

### Reporting Bugs or Suggesting Enhancements

Before creating a new issue, please **ensure one does not already exist** by searching on GitHub under [Issues](https://github.com/datalayer/jupyter-mcp-server/issues).

- If you're reporting a bug, please include a **title and clear description**, as much relevant information as possible, and a **code sample** or an **executable test case** demonstrating the expected behavior that is not occurring.
- If you're suggesting an enhancement, clearly state the enhancement you are proposing and why it would be a good addition to the project.

## Development Setup

To get started with development, you'll need to set up your environment.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/datalayer/jupyter-mcp-server
    cd jupyter-mcp-server
    ```

2.  **Install dependencies:**
    ```bash
    # Install the project in editable mode with test dependencies
    pip install -e ".[test]"
    ```

3.  **Make Some Amazing Changes!**
    ```bash
    # Make some amazing changes to the source code!
    ```

4.  **Run Tests:**
    ```bash
    make test
    ```

5.  **Build Python Package/Docker Image:**
    ```bash
    # Build the Python package
    make build
    # Build the Docker image
    make build-docker
    ```

## Testing Guidelines

This section provides comprehensive guidance for adding and maintaining tests in the Jupyter MCP Server project.

### Test Architecture

The project supports testing in two deployment modes:

1. **MCP_SERVER Mode**: Standalone MCP server using HTTP/WebSocket to connect to Jupyter
2. **JUPYTER_SERVER Mode**: Jupyter extension with direct serverapp API access

Tests are parametrized to run against both modes using the same MCPClient, ensuring consistent behavior across deployment patterns.

### Test Data

Test notebooks are located in the `dev/content/` directory:

- `notebook.ipynb`: Main test notebook with matplotlib examples and various cell types
- `new.ipynb`: Additional test notebook for multi-notebook operations

### Tool Implementation and Output Matching

When adding tests for new features or modifying existing tools, ensure your tests match the actual implementation in `jupyter_mcp_server/tools/`

## (Recommended) Manual Agent Testing

1.  **Build Python Package:**
    ```bash
    make build
    ```

2. **Set Up Your Environment:**
    ```bash
    pip install jupyterlab==4.4.1 jupyter-collaboration==4.0.2 ipykernel
    pip uninstall -y pycrdt datalayer_pycrdt
    pip install datalayer_pycrdt==0.12.17
    ```

3.  **Start Jupyter Server:**
    ```bash
    jupyter lab --port 8888 --IdentityProvider.token MY_TOKEN --ip 0.0.0.0
    ```

4.  **Set Up Your MCP Client:**
    We recommend using `uvx` to start the MCP server, first install `uvx` with `pip install uv`.

    ```bash
    pip install uv
    uv --version
    # should be 0.6.14 or higher
    ```

    Then, set up your MCP client with the following configuration file.

    ```json
    {
        "mcpServers": {
            "Jupyter-MCP": {
                "command": "uvx",
                "args": [
                    "--from",
                    "your/path/to/jupyter-mcp-server/dist/jupyter_mcp_server-x.x.x-py3-none-any.whl",
                    "jupyter-mcp-server"
                ],
                "env": {
                    "JUPYTER_URL": "http://localhost:8888",
                    "JUPYTER_TOKEN": "MY_TOKEN",
                    "ALLOW_IMG_OUTPUT": "true"
                }
            }
        }
    }
    ```

5.  **Test Your Changes:**

    You Can Test Your Changes with your favorite MCP client(e.g. Cursor, Gemini CLI, etc.).

## Pull Request Process

1.  Once you are satisfied with your changes and tests, commit your code.
2.  Push your branch to your fork and attach with detailed description of the changes you made.
3.  Open a pull request to the `main` branch of the original repository.

We look forward to your contributions!
