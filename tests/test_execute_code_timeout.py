# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Unit tests for execute_code's timeout resolution in server.py.

execute_cell and insert_execute_code_cell resolve their ``timeout`` against the
config before running: ``0`` means "use config default" (``execution_timeout``)
and any positive value is clamped to ``max_execution_timeout``. execute_code is
the third execution tool and did neither. These tests pin it to the same
contract by capturing the timeout that reaches ExecuteCodeTool, so no kernel is
required.
"""

import pytest

from jupyter_mcp_server import server
from jupyter_mcp_server.config import reset_config, set_config
from jupyter_mcp_server.tools.execute_code_tool import ExecuteCodeTool


@pytest.fixture
def captured_timeout(monkeypatch):
    """Record the timeout ExecuteCodeTool receives, so the value server.py
    resolves is observable without a running kernel. A low ceiling and a
    distinct default keep every assertion unambiguous."""
    seen = {}

    async def _fake_execute(self, *args, timeout, **kwargs):
        seen["timeout"] = timeout
        return ["ok"]

    monkeypatch.setattr(ExecuteCodeTool, "execute", _fake_execute)
    set_config(execution_timeout=45, max_execution_timeout=60)
    try:
        yield seen
    finally:
        reset_config()


async def _run(**kwargs):
    # kernel_id is supplied so timeout resolution, not kernel routing, is exercised.
    return await server.execute_code(code="1 + 1", kernel_id="k1", **kwargs)


@pytest.mark.asyncio
async def test_positive_timeout_is_clamped_to_max(captured_timeout):
    """A timeout above the operator's max_execution_timeout must be clamped down,
    not passed through, so a lowered ceiling actually binds here."""
    await _run(timeout=3600)
    assert captured_timeout["timeout"] == 60


@pytest.mark.asyncio
async def test_zero_timeout_uses_config_default(captured_timeout):
    """timeout=0 means 'use config default', as the other two execution tools
    publish; it must not reach the kernel as 0 (asyncio.wait_for(timeout=0)
    expires immediately)."""
    await _run(timeout=0)
    assert captured_timeout["timeout"] == 45


@pytest.mark.asyncio
async def test_in_range_timeout_is_passed_through(captured_timeout):
    """A positive timeout under the ceiling is honoured unchanged."""
    await _run(timeout=30)
    assert captured_timeout["timeout"] == 30


@pytest.mark.asyncio
async def test_omitted_timeout_keeps_the_default(captured_timeout):
    """Omitting timeout keeps the tool's documented default and clamps it like
    any other value (the default sits under the ceiling, so it is unchanged)."""
    await _run()
    assert captured_timeout["timeout"] == 30
