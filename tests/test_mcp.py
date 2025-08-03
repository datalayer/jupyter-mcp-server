# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

"""Python unit tests for jupyter_mcp_server."""
import pytest
import subprocess
import requests
import logging
import time
from http import HTTPStatus
from requests.exceptions import ConnectionError

JUPYTER_TOKEN="MY_TOKEN"

def _start_server(name, host, port, command, retries=5):
    _log_prefix = name
    url = f"http://{host}:{port}"
    logging.info(f"{_log_prefix}: starting ...")
    p_serv = subprocess.Popen(command, stdout=subprocess.PIPE)
    _log_prefix = f"{_log_prefix} ({p_serv.pid})"
    while retries > 0:
        try:
            response = requests.head(url)
            if response is not None:
                logging.info(f"{_log_prefix}: started ({url})!")
                time.sleep(3)
                yield url
                break
        except ConnectionError:
            logging.debug(f"{_log_prefix}: waiting to accept connections [{retries}]")
            time.sleep(1)
            retries -= 1
    if not retries:
        raise RuntimeError(f"{_log_prefix}: fail to start")
    else:
        logging.debug(f"{_log_prefix}: stopping ...")
        p_serv.terminate()
        p_serv.wait()
        logging.debug(f"{_log_prefix}: stopped")
        # Check if the process is still running
        if p_serv.poll() is None:
            logging.debug(f"{_log_prefix}: killing (graceful termination failed)")
            p_serv.kill()
            p_serv.wait()
            logging.debug(f"{_log_prefix}: killed")

@pytest.fixture(scope="session", autouse=True)
def jupyter_server():
    host="localhost"
    port=8888
    yield from _start_server(name="Jupyter Lab", host=host, port=port, 
                                command=["jupyter", "lab", "--port", str(port), "--IdentityProvider.token", JUPYTER_TOKEN, 
                                        "--ip", host, "--ServerApp.root_dir", "./dev/content", "--no-browser"
                                    ])

@pytest.fixture(scope="session")
def jupyter_mcp_server(request, jupyter_server):
    host="localhost"
    port=4040
    start_new_runtime = request.param # whether to start a kernel

    yield from _start_server(name="Jupyter MCP", host=host, port=port, 
                             command=["python", "-m", "jupyter_mcp_server", "--transport","streamable-http", 
                                  "--document-url", jupyter_server, 
                                  "--document-id", "notebook.ipynb", "--document-token", JUPYTER_TOKEN, 
                                  "--runtime-url",  jupyter_server, "--start-new-runtime", str(start_new_runtime), 
                                  "--runtime-token", JUPYTER_TOKEN, "--port",  str(port)])

def test_jupyter_health(jupyter_server):
    logging.info(f"Testing service health ({jupyter_server})")
    response = requests.get(f"{jupyter_server}/api/status", headers={
        "Authorization": f"token {JUPYTER_TOKEN}",
    })
    assert response.status_code == HTTPStatus.OK

@pytest.mark.parametrize("jupyter_mcp_server,kernel_expected_status", [(True, "alive"), (False, "not_initialized")], indirect=["jupyter_mcp_server"], ids=["start_runtime", "no_runtime"])
def test_mcp_health(jupyter_mcp_server, kernel_expected_status):
    logging.info(f"Testing MCP server health ({jupyter_mcp_server})")
    response = requests.get(f"{jupyter_mcp_server}/api/healthz")
    assert response.status_code == HTTPStatus.OK
    data = response.json()
    logging.debug(data)
    assert data.get("status") == "healthy"
    assert data.get("kernel_status") == kernel_expected_status
