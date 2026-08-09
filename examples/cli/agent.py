#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Interactive pydantic-ai CLI connected to Jupyter MCP Server."""

from __future__ import annotations

import asyncio
import os
import sys

import anyio
from pydantic_ai import Agent
from pydantic_ai._cli import (
    CustomAutoSuggest,
    FileHistory,
    PROMPT_HISTORY_FILENAME,
    PYDANTIC_AI_HOME,
    PromptSession,
    ask_agent,
    handle_slash_command,
)

try:
    # pydantic-ai >= 2.x MCP capability API
    from pydantic_ai.capabilities.mcp import MCP as MCPCapability
except ImportError:  # pragma: no cover - depends on installed pydantic-ai version
    MCPCapability = None

from prompt_toolkit.formatted_text import ANSI
from rich.console import Console

DEFAULT_MODEL = "bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_MCP_URL = "http://127.0.0.1:4040/mcp"

ANSI_RESET = "\033[0m"
ANSI_BASE = "\033[1;36m"
ANSI_SANDBOX = "\033[1;33m"


def build_cli_prog_name(
    sandbox_variant: str | None, sandbox_id: str | None, use_color: bool = True
) -> str:
    base = "jupyter-mcp-cli"
    variant = (sandbox_variant or "").strip().lower()

    def _fmt(base_text: str, sandbox_text: str) -> str:
        if not use_color:
            return f"{base_text}({sandbox_text})"
        return (
            f"{ANSI_BASE}{base_text}{ANSI_RESET}"
            f"{ANSI_SANDBOX}({sandbox_text}){ANSI_RESET}"
        )

    if variant in {"", "none", "jupyter"}:
        return _fmt(base, "none")

    sandbox_id = (sandbox_id or "").strip()
    if sandbox_id:
        return _fmt(base, f"{variant}:{sandbox_id}")
    return _fmt(base, variant)


def create_agent(model: str, mcp_url: str, mcp_token: str) -> Agent:
    headers = None
    if mcp_token:
        headers = {"Authorization": f"Bearer {mcp_token}"}

    system_prompt = (
        "You are a helpful assistant with access to Jupyter tools through MCP. "
        "Use tools when notebook state, files, code execution, or cell operations are needed."
    )

    if MCPCapability is not None:
        mcp_capability = MCPCapability(
            url=mcp_url,
            headers=headers,
        )
        return Agent(
            model=model,
            capabilities=[mcp_capability],
            system_prompt=system_prompt,
        )

    raise ImportError(
        "pydantic-ai 2.x MCP capability API not found. "
        "Install/upgrade with MCP support, e.g. `pip install -U 'pydantic-ai[mcp]'`."
    )


async def _run_colored_chat(agent: Agent, prog_name: str, prompt_label: str) -> int:
    """Run chat loop with ANSI-formatted prompt label.

    pydantic-ai's built-in to_cli currently renders prompt as a plain string.
    Using prompt_toolkit's ANSI wrapper here ensures color sequences are
    interpreted instead of printed literally.
    """

    console = Console()
    prompt_history_path = PYDANTIC_AI_HOME / PROMPT_HISTORY_FILENAME
    prompt_history_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_history_path.touch(exist_ok=True)
    session: PromptSession = PromptSession(history=FileHistory(str(prompt_history_path)))

    multiline = False
    messages = []
    prompt = ANSI(f"{prompt_label} ➤ ")

    while True:
        try:
            auto_suggest = CustomAutoSuggest(["/markdown", "/multiline", "/exit", "/cp"])
            text = await session.prompt_async(prompt, auto_suggest=auto_suggest, multiline=multiline)
        except (KeyboardInterrupt, EOFError):
            return 0

        if not text.strip():
            continue

        ident_prompt = text.lower().strip().replace(" ", "-")
        if ident_prompt.startswith("/"):
            exit_value, multiline = handle_slash_command(
                ident_prompt,
                messages,
                multiline,
                console,
                "monokai",
            )
            if exit_value is not None:
                return exit_value
        else:
            try:
                messages = await ask_agent(
                    agent,
                    text,
                    True,
                    console,
                    "monokai",
                    None,
                    messages,
                    None,
                    None,
                )
            except anyio.get_cancelled_exc_class():
                console.print("[dim]Interrupted[/dim]")
            except Exception as exc:
                cause = getattr(exc, "__cause__", None)
                console.print(f"\n[red]{type(exc).__name__}:[/red] {exc}")
                if cause:
                    console.print(f"[dim]Caused by: {cause}[/dim]")


async def _run_cli(
    model: str,
    mcp_url: str,
    mcp_token: str,
    prog_name: str,
    prompt_label: str,
    use_color: bool,
) -> None:
    agent = create_agent(model=model, mcp_url=mcp_url, mcp_token=mcp_token)
    async with agent:
        if use_color:
            await _run_colored_chat(agent=agent, prog_name=prog_name, prompt_label=prompt_label)
        else:
            await agent.to_cli(prog_name=prog_name)


def main() -> int:
    model = os.environ.get("PYDANTIC_AI_MODEL", DEFAULT_MODEL)
    mcp_url = os.environ.get("JUPYTER_MCP_URL", DEFAULT_MCP_URL)
    mcp_token = os.environ.get("MCP_TOKEN", "MY_MCP_TOKEN")
    sandbox_variant = os.environ.get("SANDBOX_VARIANT", "none")
    sandbox_id = os.environ.get("SANDBOX_ID", "")
    use_color = sys.stdout.isatty() and sys.stdin.isatty() and os.environ.get("NO_COLOR") is None
    prog_name = build_cli_prog_name(
        sandbox_variant=sandbox_variant,
        sandbox_id=sandbox_id,
        use_color=False,
    )
    prompt_label = build_cli_prog_name(
        sandbox_variant=sandbox_variant,
        sandbox_id=sandbox_id,
        use_color=use_color,
    )

    if len(sys.argv) > 1:
        model = sys.argv[1]

    print(f"Model: {model}")
    print(f"MCP URL: {mcp_url}")
    if mcp_token:
        print("MCP auth header: enabled")
    else:
        print("MCP auth header: disabled")
    print(f"CLI prompt: {prog_name}>")
    print("Starting interactive CLI. Press Ctrl+C to exit.")

    try:
        asyncio.run(
            _run_cli(
                model=model,
                mcp_url=mcp_url,
                mcp_token=mcp_token,
                prog_name=prog_name,
                prompt_label=prompt_label,
                use_color=use_color,
            )
        )
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
