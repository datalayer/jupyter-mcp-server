# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""
Pytest configuration and shared fixtures for Jupyter MCP Server tests.

This module provides:
- jupyter_server fixture: Session-scoped Jupyter Lab server
- _start_server helper: Generic server startup with health checks
- JUPYTER_TOKEN: Authentication token for Jupyter API
"""

import logging
import subprocess
import time
from http import HTTPStatus

import pytest
import requests
from requests.exceptions import ConnectionError


JUPYTER_TOKEN = "MY_TOKEN"


def _start_server(name, host, port, command, readiness_endpoint="/", max_retries=5):
    """A Helper that starts a web server as a python subprocess and wait until it's ready to accept connections

    This method can be used to start both Jupyter and Jupyter MCP servers
    """
    _log_prefix = name
    url = f"http://{host}:{port}"
    url_readiness = f"{url}{readiness_endpoint}"
    logging.info(f"{_log_prefix}: starting ...")
    p_serv = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _log_prefix = f"{_log_prefix} [{p_serv.pid}]"
    while max_retries > 0:
        try:
            response = requests.get(url_readiness, timeout=10)
            if response is not None and response.status_code == HTTPStatus.OK:
                logging.info(f"{_log_prefix}: started ({url})!")
                yield url
                break
        except (ConnectionError, requests.exceptions.Timeout):
            logging.debug(
                f"{_log_prefix}: waiting to accept connections [{max_retries}]"
            )
            time.sleep(2)
            max_retries -= 1
    if not max_retries:
        logging.error(f"{_log_prefix}: fail to start")
    logging.debug(f"{_log_prefix}: stopping ...")
    try:
        p_serv.terminate()
        p_serv.wait(timeout=5)  # Reduced timeout for faster cleanup
        logging.info(f"{_log_prefix}: stopped")
    except subprocess.TimeoutExpired:
        logging.warning(f"{_log_prefix}: terminate timeout, forcing kill")
        p_serv.kill()
        try:
            p_serv.wait(timeout=2)
        except subprocess.TimeoutExpired:
            logging.error(f"{_log_prefix}: kill timeout, process may be stuck")
    except Exception as e:
        logging.error(f"{_log_prefix}: error during shutdown: {e}")


@pytest.fixture(scope="session")
def jupyter_server():
    """Start the Jupyter server and returns its URL
    
    This is a session-scoped fixture that starts a single Jupyter Lab instance
    for all tests. Both MCP_SERVER and JUPYTER_SERVER mode tests can share this.
    """
    host = "localhost"
    port = 8888
    yield from _start_server(
        name="JupyterLab",
        host=host,
        port=port,
        command=[
            "jupyter",
            "lab",
            "--port",
            str(port),
            "--IdentityProvider.token",
            JUPYTER_TOKEN,
            "--ip",
            host,
            "--ServerApp.root_dir",
            "./dev/content",
            "--no-browser",
        ],
        readiness_endpoint="/api",
        max_retries=10,
    )
