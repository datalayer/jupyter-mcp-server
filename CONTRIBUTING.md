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

3.  **(Optional) Build the Docker image:**
    If you plan to work with Docker, you can build the image from the source:
    ```bash
    make build-docker
    ```

## Making and Testing Changes

### Automated Testing

To run the automated test suite, use `pytest`:
```bash
pytest
```

## Pull Request Process

1.  Once you are satisfied with your changes and tests, commit your code.
2.  Make sure your code lints and is formatted correctly by running `ruff check .` and `ruff format .`.
3.  Push your branch to your fork.
4.  Open a pull request to the `main` branch of the original repository.

## Styleguides

We use `ruff` for linting and formatting. Please run the following commands before submitting your pull request.

- **To check for linting errors:**
  ```bash
  ruff check .
  ```
- **To format your code:**
  ```bash
  ruff format .
  ```

We look forward to your contributions!
