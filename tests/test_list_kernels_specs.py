# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Exposing installed kernel specifications in list_kernels (#274)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jupyter_mcp_server.server import _rows
from jupyter_mcp_server.tools._base import ServerMode
from jupyter_mcp_server.tools.list_kernels_tool import ListKernelsTool

EXPECTED_HEADER = (
    "ID\tName\tDisplay_Name\tLanguage\tState\tConnections\tLast_Activity\tEnvironment"
)


def _http_spec(display_name: str, language: str, env: dict[str, str] | None = None):
    return SimpleNamespace(
        spec=SimpleNamespace(display_name=display_name, language=language, env=env or {})
    )


class FakeHttpClient:
    def __init__(self, kernels=(), specs=None):
        self.kernels = SimpleNamespace(list_kernels=lambda: list(kernels))
        self.kernelspecs = SimpleNamespace(
            list_kernelspecs=lambda: SimpleNamespace(kernelspecs=specs or {})
        )


class FakeLocalKernelManager:
    def __init__(self, kernels=()):
        self._kernels = list(kernels)

    def list_kernels(self):
        return self._kernels


class FakeLocalSpecManager:
    def __init__(self, specs=None):
        self._specs = specs or {}

    def get_all_specs(self):
        return self._specs


@pytest.mark.asyncio
async def test_list_kernels_http_exposes_specs_when_no_kernels_running():
    """Installed kernel specs appear as 'available' rows even when 0 kernels are running."""
    client = FakeHttpClient(
        kernels=[],
        specs={
            "python3": _http_spec("Python 3 (ipykernel)", "python"),
            "ir": _http_spec("R 4.3", "R", {"R_HOME": "/usr/lib/R"}),
        },
    )
    output = await ListKernelsTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=client,
    )

    assert EXPECTED_HEADER in output
    structured = _rows(output)
    assert structured["count"] == 2
    by_name = {item["Name"]: item for item in structured["items"]}
    assert by_name["python3"]["ID"] == "none"
    assert by_name["python3"]["State"] == "available"
    assert by_name["python3"]["Language"] == "python"
    assert by_name["ir"]["Display_Name"] == "R 4.3"
    assert by_name["ir"]["Language"] == "R"
    assert "R_HOME=/usr/lib/R" in by_name["ir"]["Environment"]


@pytest.mark.asyncio
async def test_list_kernels_http_combines_running_kernels_and_unstarted_specs():
    """Running kernels keep their live row; unstarted specs are listed beside them."""
    running_py = SimpleNamespace(
        id="kernel-py-1",
        name="python3",
        execution_state="idle",
        connections=1,
        last_activity="2026-11-11 12:00:00",
    )
    client = FakeHttpClient(
        kernels=[running_py],
        specs={
            "python3": _http_spec("Python 3 (ipykernel)", "python"),
            "rust": _http_spec("Rust (evcxr)", "rust"),
        },
    )
    output = await ListKernelsTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=client,
    )

    structured = _rows(output)
    assert structured["count"] == 2
    assert structured["items"][0]["ID"] == "kernel-py-1"
    assert structured["items"][0]["Name"] == "python3"
    assert structured["items"][0]["State"] == "idle"
    assert structured["items"][1]["ID"] == "none"
    assert structured["items"][1]["Name"] == "rust"
    assert structured["items"][1]["Display_Name"] == "Rust (evcxr)"
    assert structured["items"][1]["State"] == "available"


@pytest.mark.asyncio
async def test_list_kernels_local_exposes_specs_alongside_running_kernels():
    """JUPYTER_SERVER mode surfaces both running local kernels and installed kernel specs."""
    km = FakeLocalKernelManager(
        kernels=[
            {
                "id": "local-k1",
                "name": "python3",
                "execution_state": "busy",
                "connections": 2,
                "last_activity": "2026-11-11 12:05:00",
            }
        ]
    )
    ksm = FakeLocalSpecManager(
        specs={
            "python3": {"spec": {"display_name": "Python 3", "language": "python"}},
            "julia-1.10": {
                "spec": {
                    "display_name": "Julia 1.10",
                    "language": "julia",
                    "env": {"JULIA_NUM_THREADS": "4"},
                }
            },
        }
    )
    output = await ListKernelsTool().execute(
        mode=ServerMode.JUPYTER_SERVER,
        kernel_manager=km,
        kernel_spec_manager=ksm,
    )

    assert EXPECTED_HEADER in output
    structured = _rows(output)
    assert structured["count"] == 2
    assert structured["items"][0]["ID"] == "local-k1"
    assert structured["items"][0]["State"] == "busy"
    assert structured["items"][1]["ID"] == "none"
    assert structured["items"][1]["Name"] == "julia-1.10"
    assert structured["items"][1]["Language"] == "julia"
    assert structured["items"][1]["State"] == "available"
    assert "JULIA_NUM_THREADS=4" in structured["items"][1]["Environment"]


@pytest.mark.asyncio
async def test_list_kernels_returns_empty_message_when_neither_kernels_nor_specs_exist():
    client = FakeHttpClient(kernels=[], specs={})
    output = await ListKernelsTool().execute(
        mode=ServerMode.MCP_SERVER,
        sandbox_server_client=client,
    )
    assert output == "No kernels found on the Jupyter server."
