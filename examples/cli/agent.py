#!/usr/bin/env python3
# Copyright (c) 2025-2026 Datalayer, Inc.
# Distributed under the terms of the Modified BSD License.

"""Interactive pydantic-ai CLI connected to Jupyter MCP Server."""

from __future__ import annotations

import asyncio
import os
import sys

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP


DEFAULT_MODEL = "bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_MCP_URL = "http://127.0.0.1:4040/mcp"


def create_agent(model: str, mcp_url: str, mcp_token: str) -> Agent:
    headers = None
    if mcp_token:
        headers = {"Authorization": f"Bearer {mcp_token}"}

    mcp_server = MCPServerStreamableHTTP(
        url=mcp_url,
        headers=headers,
        timeout=300.0,
    )

    return Agent(
        model=model,
        toolsets=[mcp_server],
        system_prompt=(
            "You are a helpful assistant with access to Jupyter tools through MCP. "
            "Use tools when notebook state, files, code execution, or cell operations are needed."
        ),
    )


async def _run_cli(model: str, mcp_url: str, mcp_token: str) -> None:
    agent = create_agent(model=model, mcp_url=mcp_url, mcp_token=mcp_token)
    async with agent:
        await agent.to_cli(prog_name="jupyter-mcp-cli")


def main() -> int:
    model = os.environ.get("PYDANTIC_AI_MODEL", DEFAULT_MODEL)
    mcp_url = os.environ.get("JUPYTER_MCP_URL", DEFAULT_MCP_URL)
    mcp_token = os.environ.get("MCP_TOKEN", "MY_MCP_TOKEN")

    if len(sys.argv) > 1:
        model = sys.argv[1]

    print(f"Model: {model}")
    print(f"MCP URL: {mcp_url}")
    if mcp_token:
        print("MCP auth header: enabled")
    else:
        print("MCP auth header: disabled")
    print("Starting interactive CLI. Press Ctrl+C to exit.")

    try:
        asyncio.run(_run_cli(model=model, mcp_url=mcp_url, mcp_token=mcp_token))
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 0
    except Exception as err:
        print(f"Error: {err}")
        print("Hint: ensure Jupyter MCP Server is running and MCP_TOKEN matches.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())