# Jupyter MCP Server

**Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.**

Jupyter MCP Server is a Python-based Model Context Protocol (MCP) server implementation that enables real-time interaction with Jupyter Notebooks. The project uses a modern Python build system with hatch, and includes comprehensive testing, linting, and documentation.

## Working Effectively

### Environment Setup
- **Python Requirements**: Python 3.10 or higher (tested with 3.9-3.13)
- **Network Considerations**: PyPI installs may fail due to SSL certificate issues or timeout limitations. This is a known environment constraint.

### Build and Install (CRITICAL: Network Limitations)
```bash
# Standard installation (may fail with network issues)
pip install ".[test,lint,typing]"

# Alternative if pip install fails:
# 1. Install dependencies individually with longer timeouts
pip install --timeout=300 pytest
pip install --timeout=300 ruff  
pip install --timeout=300 mypy

# 2. Or use Docker approach (preferred for consistency)
docker build -t jupyter-mcp-server .
```

**NETWORK TIMEOUT WARNING**: pip install commands may fail with SSL certificate errors or read timeouts when connecting to PyPI. If installs fail:
- Try increasing timeout: `pip install --timeout=300`
- Use Docker build which handles dependencies internally
- Document the network limitation in any testing notes

### Core Development Commands
```bash
# Development installation (when network allows)
make dev
# Equivalent to: pip install ".[test,lint,typing]"

# Basic installation  
make install
# Equivalent to: pip install .

# Build the package
make build
# Equivalent to: pip install build && python -m build .
```

### Testing (CRITICAL: Use Long Timeouts)
```bash
# Run tests using hatch (when available)
make test
# Equivalent to: hatch test

# Run tests directly with pytest (when network allows install)
pytest .

# NEVER CANCEL: Test suite timing expectations
# - Full test suite: Allow 15-20 minutes minimum
# - Network-dependent tests may take longer
# - Set timeout to 30+ minutes for safety
```

**VALIDATION REQUIREMENT**: When testing is not possible due to network issues, verify at minimum:
```bash
# Syntax validation (always works)
python -m py_compile jupyter_mcp_server/server.py
find . -name "*.py" -exec python -m py_compile {} \;

# Import validation
PYTHONPATH=. python -c "import jupyter_mcp_server; print('Import successful')"
```

### Linting and Code Quality (CRITICAL: Use Long Timeouts)
```bash
# Full linting pipeline (when network allows)
bash ./.github/workflows/lint.sh

# Individual linting commands:
pip install -e ".[lint,typing]"
mypy --install-types --non-interactive .  # May take 10+ minutes, NEVER CANCEL
ruff check .                              # Quick, usually <1 minute  
mdformat --check *.md                     # Quick, usually <1 minute
pipx run 'validate-pyproject[all]' pyproject.toml  # 2-3 minutes

# TIMING WARNING: mypy type checking can take 10+ minutes on first run
# Set timeout to 20+ minutes for mypy operations
```

### Running the Application

#### Local Development Mode
```bash
# Start with streamable HTTP transport
make start
# Equivalent to:
jupyter-mcp-server start \
  --transport streamable-http \
  --document-url http://localhost:8888 \
  --document-id notebook.ipynb \
  --document-token MY_TOKEN \
  --runtime-url http://localhost:8888 \
  --start-new-runtime true \
  --runtime-token MY_TOKEN \
  --port 4040
```

#### JupyterLab Setup (Required for Testing)
```bash
# Start JupyterLab server for MCP integration
make jupyterlab
# Equivalent to:
pip uninstall -y pycrdt datalayer_pycrdt
pip install datalayer_pycrdt
jupyter lab \
  --port 8888 \
  --ip 0.0.0.0 \
  --ServerApp.root_dir ./dev/content \
  --IdentityProvider.token MY_TOKEN
```

#### Docker Deployment
```bash
# Build Docker image (NEVER CANCEL: Build takes 10-15 minutes)
make build-docker  # Takes 10-15 minutes, set timeout to 20+ minutes

# Run with Docker  
make start-docker
# Or manually:
docker run -i --rm \
  -e DOCUMENT_URL=http://localhost:8888 \
  -e DOCUMENT_ID=notebook.ipynb \
  -e DOCUMENT_TOKEN=MY_TOKEN \
  -e RUNTIME_URL=http://localhost:8888 \
  -e START_NEW_RUNTIME=true \
  -e RUNTIME_TOKEN=MY_TOKEN \
  --network=host \
  datalayer/jupyter-mcp-server:latest
```

### Manual Validation Scenarios

**When full testing is not possible due to network constraints, always verify:**

1. **Syntax and Import Validation**:
   ```bash
   # Validate all Python files compile
   find . -name "*.py" -exec python -m py_compile {} \;
   
   # Test local imports work
   PYTHONPATH=. python -c "import jupyter_mcp_server; print('SUCCESS')"
   ```

2. **Configuration Validation**:
   ```bash
   # Verify pyproject.toml is valid
   python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"
   
   # Test module structure
   python -c "import jupyter_mcp_server.server, jupyter_mcp_server.models"
   ```

3. **Documentation Build** (when Node.js available):
   ```bash
   cd docs/
   npm install  # May have network issues
   npm run build  # 3-5 minutes, set timeout to 10+ minutes
   ```

## Project Structure and Navigation

### Key Directories
- **`jupyter_mcp_server/`**: Main Python package
  - `server.py`: Core MCP server implementation with FastMCP integration
  - `models.py`: Pydantic data models for document and runtime handling
  - `utils.py`: Utility functions for output extraction and processing
  - `tests/`: Unit tests (internal package tests)
- **`tests/`**: Integration tests using pytest-asyncio
- **`docs/`**: Docusaurus-based documentation site (Node.js/React)
- **`dev/content/`**: Development Jupyter notebook files for testing
- **`.github/workflows/`**: CI/CD pipeline definitions

### Important Files
- **`pyproject.toml`**: Build configuration, dependencies, and tool settings
- **`Makefile`**: Development workflow automation
- **`Dockerfile`**: Container build definition
- **`.github/workflows/lint.sh`**: Linting pipeline script
- **`pytest.ini`**: Test configuration

### Frequently Modified Areas
- **Server Logic**: `jupyter_mcp_server/server.py` - Main MCP server implementation
- **Data Models**: `jupyter_mcp_server/models.py` - When adding new MCP tools or changing data structures
- **Tests**: `tests/test_mcp.py` - Integration tests for MCP functionality
- **Documentation**: `docs/src/` - When updating API documentation or user guides

## Common Tasks and Gotchas

### Adding New MCP Tools
1. Add tool definition in `jupyter_mcp_server/server.py`
2. Update models in `jupyter_mcp_server/models.py` if needed
3. Add tests in `tests/test_mcp.py`
4. Update documentation in `docs/`

### Dependency Management
- **Core deps**: Defined in `pyproject.toml` dependencies section
- **Dev deps**: Use `[test,lint,typing]` optional dependencies
- **Special handling**: `datalayer_pycrdt` has specific version requirements (0.12.17)

### CI/CD Pipeline Expectations
- **Build Matrix**: Tests run on Ubuntu, macOS, Windows with Python 3.9, 3.13
- **Critical Timing**: Full CI pipeline takes 20-30 minutes
- **Required Checks**: pytest, ruff, mypy, mdformat, pyproject validation

### Environment Variables for Testing
```bash
# Required for MCP server operation
export DOCUMENT_URL="http://localhost:8888"
export DOCUMENT_TOKEN="MY_TOKEN"
export DOCUMENT_ID="notebook.ipynb"
export RUNTIME_URL="http://localhost:8888"
export RUNTIME_TOKEN="MY_TOKEN"
```

## Network Limitations and Workarounds

**CRITICAL CONSTRAINT**: This development environment has limited PyPI connectivity with SSL certificate issues and timeout problems.

### Known Working Commands
```bash
# These always work (no network required):
python -m py_compile <file>          # Syntax validation
PYTHONPATH=. python -c "import ..."  # Import testing  
python -c "import tomllib; ..."      # Config validation
git operations                       # Version control
docker build (when base images cached)
```

### Commands That May Fail
```bash
pip install <anything>               # Network timeouts/SSL issues
npm install                          # Network limitations  
mypy --install-types                 # Downloads type stubs
hatch test                           # May need PyPI for dependencies
```

### Required Workarounds
1. **Document network failures** when they occur: "pip install fails due to network limitations"
2. **Use syntax validation** instead of full testing when pip installs fail
3. **Prefer Docker approach** for consistent builds when possible
4. **Set generous timeouts** (60+ minutes) for any network operations
5. **Never cancel long-running commands** - document expected timing instead

## Timing Expectations

**NEVER CANCEL these operations - they are expected to take significant time:**

- **pip install ".[test,lint,typing]"**: 5-10 minutes (when network works)
- **mypy --install-types --non-interactive**: 10-15 minutes first run
- **Docker build**: 10-15 minutes
- **Full test suite**: 15-20 minutes  
- **Documentation build**: 3-5 minutes
- **CI pipeline**: 20-30 minutes total

Always set timeouts to at least double these estimates to account for network variability.