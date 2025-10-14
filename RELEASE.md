# 🚀 Jupyter MCP Server Release Guide

This document provides detailed instructions on how to release the Jupyter MCP Server project using GitHub Actions.

## 📋 Release Process Overview

The release process is defined in the `.github/workflows/release.yml` file and includes the following automated steps:

1. **Python Package Build** - Build distribution packages (wheel and source distribution)
2. **PyPI Publishing** - Automatically publish to PyPI (using OIDC trusted publishing)
3. **Docker Image Build** - Build multi-platform Docker images
4. **GitHub Release Creation** - Automatically generate release notes (simplified version, without automatic changelog)

## 🔖 Version Management

### Semantic Versioning
The project uses semantic versioning format: `v{major}.{minor}.{patch}`

Examples:
- `v1.0.0` - Major version update
- `v1.1.0` - Minor feature update
- `v1.1.1` - Patch and bug fixes

### Version Tags
For releases, you need to push Git tags with version numbers:

```bash
# Create and push version tag
git tag v1.0.0
git push origin v1.0.0
```

## ⚙️ Release Workflow Trigger Conditions

The workflow is automatically triggered when:
- Pushing Git tags in the format `v*.*.*` (e.g., `v1.0.0`, `v2.1.3`)

**Configuration Steps:**

1. Configure Trusted Publisher in PyPI project settings
   - Go to https://pypi.org/manage/project/jupyter-mcp-server/settings/publishing/
   - Add GitHub Actions as a trusted publisher
   - Configure:
     - Owner: `datalayer`
     - Repository: `jupyter-mcp-server`
     - Workflow: `release.yml`
     - Environment: `pypi`

2. GitHub repository settings
   - Settings → Environments → New environment: `pypi`
   - Configure protection rules (optional):
     - Required reviewers (requires approval)
     - Branch protection (only allows main branch)

Creating access token in Docker Hub:
- Settings → Security → Access Tokens
- Create restricted token (read/write only specific repository)
- Store as GitHub Secret:
    - `DOCKERHUB_USERNAME` - Docker Hub username
    - `DOCKERHUB_TOKEN` - Docker Hub access token

### GitHub Release
- Uses built-in `GITHUB_TOKEN`, no additional configuration required

## 📦 Release Artifacts

### Python Package
- **PyPI**: `https://pypi.org/project/jupyter-mcp-server/`
- **Formats**: wheel (`.whl`) and source distribution (`.tar.gz`)

### Docker Image
- **Repository**: `datalayer/jupyter-mcp-server`
- **Tags**:
  - `latest` - Latest stable version
  - `{version}` - Specific version number (e.g., `1.0.0`)

## 🔄 Release Steps

1. **Update Version Number**
   ```bash
   # Edit version file
   vim jupyter_mcp_server/__version__.py
   ```

2. **Create Release Tag**
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

3. **Monitor Release Progress**
   - Go to GitHub Actions page to view workflow run status
   - Check if PyPI has been updated
   - Verify Docker Hub has new images

## 🔄 Version Rollback

If serious issues occur during release:

1. **Delete GitHub Release** (if created)
2. **Delete package from PyPI** (if published) - Requires admin privileges
3. **Delete Docker image tags from Docker Hub**
4. **Push new tag to re-release**
