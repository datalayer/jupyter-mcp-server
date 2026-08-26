# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The CLI example, driven without an LLM.

``agent.py`` wires pydantic-ai to the Jupyter MCP Server, and the wiring is
what breaks: the capability not connecting, the bearer token not being sent,
a tool call not reaching a kernel. pydantic-ai's test models stand in for the
model, so this runs anywhere — no API key, nothing beyond localhost.
"""

from __future__ import annotations

import pytest
from agent import build_cli_prog_name, create_agent, create_mcp_capability
from conftest import MCP_TOKEN
from mcp.shared.exceptions import MCPError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel


class TestPromptLabel:
    def test_no_sandbox(self):
        assert build_cli_prog_name(None, None, use_color=False) == "jupyter-mcp-cli(none)"
        assert build_cli_prog_name("jupyter-server", "", use_color=False) == "jupyter-mcp-cli(none)"

    def test_a_variant_and_its_id(self):
        assert build_cli_prog_name("e2b", None, use_color=False) == "jupyter-mcp-cli(e2b)"
        assert build_cli_prog_name("e2b", "sb-1", use_color=False) == "jupyter-mcp-cli(e2b:sb-1)"
        assert (
            build_cli_prog_name("google_colab", "", use_color=False)
            == "jupyter-mcp-cli(google-colab)"
        )

    def test_color_is_ansi_around_the_same_text(self):
        colored = build_cli_prog_name("e2b", "sb-1", use_color=True)
        assert colored.startswith("\033[") and colored.endswith("\033[0m")
        assert "jupyter-mcp-cli" in colored and "(e2b:sb-1)" in colored


class TestCapability:
    def test_points_at_the_server_with_the_token(self):
        capability = create_mcp_capability("http://127.0.0.1:1/mcp", "secret")
        assert capability.url == "http://127.0.0.1:1/mcp"
        assert capability.headers == {"Authorization": "Bearer secret"}

    def test_sends_no_header_without_a_token(self):
        assert create_mcp_capability("http://127.0.0.1:1/mcp", "").headers is None


@pytest.mark.asyncio
async def test_the_agent_is_offered_the_jupyter_tools(mcp_url):
    """The model sees the server's tools, which is the connection working end to end."""
    model = TestModel(call_tools=[])
    agent = create_agent(model=model, mcp_url=mcp_url, mcp_token=MCP_TOKEN)
    async with agent:
        await agent.run("What can you do?")
    offered = {tool.name for tool in model.last_model_request_parameters.function_tools}
    assert {"list_files", "list_kernels", "use_notebook", "execute_code", "read_cell"} <= offered


@pytest.mark.asyncio
async def test_a_tool_call_runs_on_the_kernel(mcp_url):
    """A scripted model calls ``execute_code``; the answer comes back from a real kernel."""

    def scripted_model(messages, info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("execute_code", {"code": "print(6 * 7)"})])
        return ModelResponse(parts=[TextPart("The kernel says 42.")])

    agent = create_agent(model=FunctionModel(scripted_model), mcp_url=mcp_url, mcp_token=MCP_TOKEN)
    async with agent:
        result = await agent.run("Compute 6 * 7 on the kernel.")

    returns = [
        part
        for message in result.all_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert [part.tool_name for part in returns] == ["execute_code"]
    assert "42" in str(returns[0].content)
    assert result.output == "The kernel says 42."


@pytest.mark.asyncio
async def test_the_wrong_token_is_refused(mcp_url):
    """The header the CLI sends is what authenticates it; a bad one gets nowhere."""
    agent = create_agent(model=TestModel(call_tools=[]), mcp_url=mcp_url, mcp_token="not-the-token")
    with pytest.raises(Exception) as excinfo:
        async with agent:
            await agent.run("What can you do?")
    assert _mentions_rejection(excinfo.value), repr(excinfo.value)


def _mentions_rejection(error: BaseException) -> bool:
    """Whether *error*, or anything it wraps, is the server turning the client away."""
    text = str(error).lower()
    if "401" in text or "unauthorized" in text or "error response" in text:
        return True
    if isinstance(error, MCPError):
        return True
    nested = [*getattr(error, "exceptions", ()), error.__cause__, error.__context__]
    return any(_mentions_rejection(e) for e in nested if e is not None)
