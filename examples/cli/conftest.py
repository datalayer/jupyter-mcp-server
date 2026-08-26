# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""What the CLI example talks to, started the way ``make start`` starts it.

A JupyterLab and a Jupyter MCP Server, each a subprocess, the same commands the
Makefile runs. The LLM is the one thing left out: the tests drive the agent
with pydantic-ai's test models, so they need no API key and run in CI.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import requests

JUPYTER_TOKEN = "MY_TOKEN"
MCP_TOKEN = "MY_MCP_TOKEN"
HOST = "127.0.0.1"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _serve(
    name: str, command: list[str], readiness_url: str, log: Path, timeout: float = 120
) -> Iterator[None]:
    """Run *command* until the test session is over.

    Yields once *readiness_url* answers 200. A process that exits, or never
    answers, fails the session with the tail of its output, which is what
    one needs to see when a server does not come up on CI.
    """
    with log.open("w") as fh:
        proc = subprocess.Popen(command, stdout=fh, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if proc.poll() is not None:
                pytest.fail(f"{name} exited with {proc.returncode}:\n{log.read_text()[-4000:]}")
            try:
                if requests.get(readiness_url, timeout=5).status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"{name} not ready after {timeout}s:\n{log.read_text()[-4000:]}")
            time.sleep(1)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture(scope="session")
def notebook_dir(tmp_path_factory) -> Path:
    """A working copy of the notebook the example opens, so tests leave the checkout alone."""
    root = tmp_path_factory.mktemp("content")
    shutil.copy(REPO_ROOT / "dev" / "content" / "notebook.ipynb", root / "notebook.ipynb")
    return root


@pytest.fixture(scope="session")
def jupyter_url(notebook_dir: Path, tmp_path_factory) -> Iterator[str]:
    port = _free_port()
    url = f"http://{HOST}:{port}"
    command = [
        sys.executable,
        "-m",
        "jupyterlab",
        "--port",
        str(port),
        "--ip",
        HOST,
        "--IdentityProvider.token",
        JUPYTER_TOKEN,
        "--ServerApp.root_dir",
        str(notebook_dir),
        "--ServerApp.port_retries",
        "0",
        "--no-browser",
    ]
    log = tmp_path_factory.mktemp("logs") / "jupyter.log"
    yield from (url for _ in _serve("JupyterLab", command, f"{url}/api", log))


@pytest.fixture(scope="session")
def mcp_url(jupyter_url: str, tmp_path_factory) -> Iterator[str]:
    """The MCP endpoint, authenticated with :data:`MCP_TOKEN` as ``make start`` is."""
    port = _free_port()
    base = f"http://{HOST}:{port}"
    command = [
        sys.executable,
        "-m",
        "jupyter_mcp_server",
        "start",
        "--transport",
        "streamable-http",
        "--jupyter-url",
        jupyter_url,
        "--jupyter-token",
        JUPYTER_TOKEN,
        "--document-id",
        "notebook.ipynb",
        "--start-new-code-sandbox",
        "true",
        "--mcp-token",
        MCP_TOKEN,
        "--port",
        str(port),
    ]
    log = tmp_path_factory.mktemp("logs") / "mcp.log"
    server = _serve("Jupyter MCP Server", command, f"{base}/api/healthz", log)
    yield from (f"{base}/mcp" for _ in server)
