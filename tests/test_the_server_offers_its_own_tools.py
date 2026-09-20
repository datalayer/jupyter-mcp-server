# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""This server's own tools are contributions like anybody else's.

Two things follow from that, and neither was possible while a tool was only a
decorator on one module-level server:

* a host can build a server that *has* them — the whole point of building one
  per set of toolsets, and without this such a server would carry every
  extension's tools and none of the notebook tools;
* an extension can narrow one by name, instead of reaching into a live
  server's tool manager to take the original off and register a replacement.

Launch the tests:
```
$ pytest tests/test_the_server_offers_its_own_tools.py -v
```
"""

from __future__ import annotations

from typing import Any

import pytest
from reactor import PluginCompatibility, PluginManifest
from reactor_mcp_server import McpExtension, ToolExtension

from jupyter_mcp_server.core_tools import CORE_TOOLSET, CoreToolsExtension
from jupyter_mcp_server.extensions import ExtensionManager
from jupyter_mcp_server.server import SCAFFOLD_TOOLS, mcp


class TestWhatTheServerShips:
    def test_the_snapshot_names_the_decorated_tools(self):
        """Taken at import, so it is the server's own and nobody else's."""
        assert "execute_cell" in SCAFFOLD_TOOLS
        assert "use_notebook" in SCAFFOLD_TOOLS
        assert "list_notebooks" in SCAFFOLD_TOOLS

    def test_every_one_of_them_is_offered(self):
        offered = {spec.name for spec in CoreToolsExtension().tools()}
        assert set(SCAFFOLD_TOOLS) == offered

    def test_they_keep_what_they_told_a_client_about_themselves(self):
        specs = {spec.name: spec for spec in CoreToolsExtension().tools()}
        spec = specs["execute_cell"]
        tool = mcp._tool_manager.get_tool("execute_cell")
        assert spec.documentation == tool.description
        assert spec.annotations == tool.annotations

    def test_they_are_one_toolset_a_client_can_ask_for(self):
        extension = CoreToolsExtension()
        assert [toolset.name for toolset in extension.toolsets()] == [CORE_TOOLSET]
        assert all(spec.toolset == CORE_TOOLSET for spec in extension.tools())

    def test_lifting_happens_once(self):
        """Twice would read a server that resolved tools are now on, and
        offer each of them a second time — extended twice over."""
        extension = CoreToolsExtension()
        assert extension.tools() is extension.tools()


class TestAHostBuildsAServerThatHasThem:
    def test_the_manager_registers_it_without_being_asked(self):
        manager = ExtensionManager()
        manager.discover()
        assert manager.get("jupyter-mcp-server") is not None

    def test_a_built_server_carries_the_notebook_tools(self):
        manager = ExtensionManager()
        manager.discover()
        built = manager.host.build()
        assert "execute_cell" in built.tool_names
        assert "read_cell" in built.tool_names

    def test_a_client_can_ask_for_them_alone(self):
        from reactor_mcp_server import parse_selection

        manager = ExtensionManager()
        manager.discover()
        built = manager.host.build(parse_selection(f"only={CORE_TOOLSET}"))
        assert set(built.tool_names) == set(SCAFFOLD_TOOLS)


class TestABuiltServerIsFurnished:
    """A built server is not only its tools.

    `initialize` is where a client learns whether this server does
    subscriptions, and a client that reads "no" does not then ask — so a
    built server missing the handler is worse than one missing a tool, which
    at least fails loudly when something calls it.
    """

    @pytest.fixture(scope="class")
    def built(self):
        manager = ExtensionManager()
        manager.discover()
        return manager.host.build().server

    def test_it_serves_the_methods_this_server_added(self, built):
        from mcp.server.mcpserver import MCPServer

        added = set(built._lowlevel_server._request_handlers) - set(
            MCPServer("bare")._lowlevel_server._request_handlers
        )
        assert {"resources/subscribe", "resources/unsubscribe", "logging/setLevel"} <= added

    def test_and_says_so_when_a_client_asks(self, built):
        capabilities = built._lowlevel_server.get_capabilities(
            notification_options=None, experimental_capabilities={}
        )
        assert capabilities.resources.subscribe is True

    def test_it_has_the_resources(self, built):
        assert "capabilities://" in built._resource_manager._resources
        assert built._resource_manager._templates

    def test_it_has_the_prompt(self, built):
        assert "jupyter_cite" in built._prompt_manager._prompts

    def test_it_has_the_management_routes(self, built):
        served = {getattr(route, "path", None) for route in built._custom_starlette_routes}
        assert {"/api/healthz", "/api/connect", "/api/stop"} <= served

    def test_what_the_built_server_already_had_is_not_replaced(self):
        """An extension that put its own `capabilities://` on the server it
        was handed meant that one."""
        from mcp.server.mcpserver import MCPServer

        from jupyter_mcp_server.core_tools import furnish
        from jupyter_mcp_server.server import mcp

        target = MCPServer("target")
        mine = object()
        target._resource_manager._resources["capabilities://"] = mine
        furnish(target, mcp)
        assert target._resource_manager._resources["capabilities://"] is mine

    def test_furnishing_the_module_server_is_not_attempted(self):
        """It has its own, and putting them back is a duplicate registration
        at best."""
        from jupyter_mcp_server.server import mcp

        before = dict(mcp._resource_manager._resources)
        CoreToolsExtension().on_server(mcp)
        assert mcp._resource_manager._resources == before


class Narrows(McpExtension):
    """An extension of a tool the server itself ships."""

    def manifest(self) -> Any:
        return PluginManifest(
            name="narrows",
            version="0.0.1",
            compatibility=PluginCompatibility(api_version="v1"),
        )

    def tool_extensions(self) -> Any:
        def wrap(original: Any) -> Any:
            async def execute_cell(cell_id: str = "") -> str:
                return "narrowed"

            return execute_cell

        return (
            (
                "execute_cell",
                ToolExtension(wrap=wrap, description="Narrowed by a test."),
            ),
        )


class TestAnExtensionNarrowsOneOfThem:
    """What used to mean reaching into the server's tool manager."""

    def test_the_extension_applies(self):
        manager = ExtensionManager()
        manager.discover()
        manager.register(Narrows())
        built = manager.host.build()
        spec = {item.name: item for item in built.tools}["execute_cell"]
        assert spec.documentation == "Narrowed by a test."

    @pytest.mark.asyncio
    async def test_and_it_is_what_a_caller_reaches(self):
        manager = ExtensionManager()
        manager.discover()
        manager.register(Narrows())
        built = manager.host.build()
        result = await built.server.call_tool("execute_cell", {})
        assert "narrowed" in str(result)


class Counts(McpExtension):
    """An extension with work to do once, when the server is put together."""

    started = 0

    def manifest(self) -> Any:
        return PluginManifest(
            name="counts",
            version="0.0.1",
            compatibility=PluginCompatibility(api_version="v1"),
        )

    def on_start(self) -> None:
        Counts.started += 1


class TestTheExtensionsAreStarted:
    """`on_start` is where an extension registers a hook or opens a client.

    Nothing started the platform, so it was a hook the documentation
    described and no entry point ever reached — and an extension that
    registered an execution hook there registered it nowhere.
    """

    def test_registering_the_tools_starts_them(self):
        from jupyter_mcp_server import server

        Counts.started = 0
        server.extension_manager.register(Counts())
        try:
            server.register_extension_tools()
            assert Counts.started == 1
        finally:
            server.extension_manager.stop()

    def test_and_starting_twice_starts_nothing_twice(self):
        """Every entry point calls it, and one of them is a tool listing."""
        from jupyter_mcp_server import server

        Counts.started = 0
        server.extension_manager.register(Counts())
        try:
            server.register_extension_tools()
            server.register_extension_tools()
            assert Counts.started == 1
        finally:
            server.extension_manager.stop()
