# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Which tools an agent is offered, and what they mean.

An agent works from the tool list. Offer it a tool that always fails and it
keeps trying, then invents an explanation — a hosted session offering to
connect to a Jupyter on the user's laptop is what that looks like. So the list
itself is the thing under test here.
"""

from __future__ import annotations

import pytest
from jupyter_mcp_spaces import SpacesExtension
from jupyter_mcp_spaces.extension import JUPYTER_ONLY_TOOLS
from mcp.server import MCPServer


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    """The server's configuration, as the extension reads it."""

    def _set(provider="datalayer"):
        from jupyter_mcp_server.config import set_config

        set_config(document_provider=provider, document_url="https://spacer.test")

    _set()
    yield _set
    from jupyter_mcp_server.config import reset_config

    reset_config()


def _server_with_upstream_tools() -> MCPServer:
    """A server carrying the tools the open source project registers."""
    mcp = MCPServer("test")

    @mcp.tool()
    def list_files() -> str:
        """Upstream: lists a Jupyter directory."""
        return "files"

    @mcp.tool()
    def list_kernels() -> str:
        """Upstream: lists Jupyter kernels."""
        return "kernels"

    @mcp.tool()
    def connect_to_jupyter() -> str:
        """Upstream: connects to a Jupyter server."""
        return "connected"

    @mcp.tool()
    def list_notebooks() -> str:
        """Upstream: notebooks bound in this session."""
        return "No managed notebooks."

    return mcp


async def _names(mcp: MCPServer) -> list[str]:
    return [tool.name for tool in await mcp.list_tools()]


class TestTheToolList:
    @pytest.mark.asyncio
    async def test_the_jupyter_only_tools_are_hidden(self):
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        names = await _names(mcp)
        for hidden in JUPYTER_ONLY_TOOLS:
            assert hidden not in names

    @pytest.mark.asyncio
    async def test_list_notebooks_is_replaced_not_shadowed(self):
        """The failure this guards against is silent.

        MCPServer warns "Tool already exists" and *keeps the original*, so a
        replacement registered on a live name does nothing at all — the agent
        still gets the session registry, still reports no notebooks, and
        nothing in the logs says why.
        """
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        tool = mcp._tool_manager._tools["list_notebooks"]
        assert "Datalayer spaces" in tool.description
        assert "bound in this session" not in tool.description

    @pytest.mark.asyncio
    async def test_the_spaces_tools_are_added(self):
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        names = await _names(mcp)
        assert "list_spaces" in names
        assert "list_notebooks" in names
        assert "find_notebook" in names

    @pytest.mark.asyncio
    async def test_a_jupyter_server_is_left_untouched(self, _config):
        """Pointed at a Jupyter, its own tools are the right ones.

        Replacing them there would break the ordinary single-user case this
        project exists for.
        """
        _config(provider="jupyter")
        mcp = _server_with_upstream_tools()
        SpacesExtension().register_tools(mcp)
        names = await _names(mcp)
        for kept in JUPYTER_ONLY_TOOLS:
            assert kept in names
        assert "list_spaces" not in names

    @pytest.mark.asyncio
    async def test_registering_twice_is_harmless(self):
        # Removing a tool that is already gone raises in MCPServer, so a second
        # pass must not take the server down.
        mcp = _server_with_upstream_tools()
        extension = SpacesExtension()
        extension.register_tools(mcp)
        extension.register_tools(mcp)
        assert "list_spaces" in await _names(mcp)

    @pytest.mark.asyncio
    async def test_a_server_without_those_tools_is_fine(self):
        # An upstream release may rename one. That must not stop startup.
        mcp = MCPServer("bare")
        SpacesExtension().register_tools(mcp)
        assert "list_notebooks" in await _names(mcp)


class TestActivationAtImportTime:
    """When the extension decides, and what it can know by then.

    This used to be decided at *import* time, which was earlier than it
    looked: the server registered extensions at module scope, so the decision
    ran while the CLI was still parsing arguments and before `set_config`.
    Asking the configuration alone always answered "jupyter", so the
    extension registered nothing, hid nothing, and said nothing about why —
    the agent then reported "no managed notebooks" and offered to connect to
    a local Jupyter. The workaround was to read `sys.argv` here.

    Registration now happens after configuration
    (`jupyter_mcp_server.server.register_extension_tools`), so the
    configuration is simply the answer and `sys.argv` is not consulted at all.
    """

    def test_the_configuration_decides(self, monkeypatch):
        from jupyter_mcp_spaces.extension import _serving_datalayer

        from jupyter_mcp_server.config import reset_config, set_config

        reset_config()
        monkeypatch.delenv("DOCUMENT_PROVIDER", raising=False)
        set_config(document_provider="datalayer")
        assert _serving_datalayer()

    def test_the_environment_is_enough(self, monkeypatch):
        """A deployment sets it, and it is read before the CLI has been given
        anything to configure from."""
        from jupyter_mcp_spaces.extension import _serving_datalayer

        from jupyter_mcp_server.config import reset_config

        reset_config()
        monkeypatch.setenv("DOCUMENT_PROVIDER", "datalayer")
        assert _serving_datalayer()

    def test_a_jupyter_server_stays_a_jupyter_server(self, monkeypatch):
        from jupyter_mcp_spaces.extension import _serving_datalayer

        from jupyter_mcp_server.config import reset_config

        reset_config()
        monkeypatch.delenv("DOCUMENT_PROVIDER", raising=False)
        assert not _serving_datalayer()

    def test_the_command_line_is_no_longer_read(self, monkeypatch):
        """The workaround is gone, and must not creep back. Reading argv
        here was always wrong — it duplicated the CLI's own parsing, and got
        the short forms and joined forms right only by luck."""
        import ast
        import inspect

        from jupyter_mcp_spaces import extension

        # The body, not the docstring: the docstring says what it used to do,
        # and that history is worth keeping.
        tree = ast.parse(inspect.getsource(extension._serving_datalayer))
        body = ast.dump(ast.Module(body=tree.body[0].body[1:], type_ignores=[]))
        assert "argv" not in body
        assert not hasattr(extension, "sys"), "the module no longer needs sys at all"

        from jupyter_mcp_server.config import reset_config

        reset_config()
        monkeypatch.delenv("DOCUMENT_PROVIDER", raising=False)
        monkeypatch.setattr(
            "sys.argv", ["jupyter-mcp-server", "start", "--document-provider", "datalayer"]
        )
        # The command line no longer decides it; the configuration the CLI
        # builds from that command line does, and it has not been built yet.
        assert not _serving_datalayer_of(extension)


def _serving_datalayer_of(module):
    return module._serving_datalayer()


class TestUseNotebookByName:
    """A uid is not something a person says out loud.

    An agent asked to open "welcome to datalayer" has a name, not an
    identifier. Requiring the uid means it either asks the user to go and find
    one, or guesses — and a guessed uid opens nothing.
    """

    @staticmethod
    def _notebooks():
        return [
            {"uid": "ntb-1", "name": "Welcome to Datalayer — Notebook",
             "notebook_name": "welcome_to_datalayer", "space": "Welcome"},
            {"uid": "ntb-2", "name": "Sales forecast",
             "notebook_name": "sales_forecast", "space": "Team"},
            {"uid": "ntb-3", "name": "Sales forecast v2",
             "notebook_name": "sales_forecast_v2", "space": "Team"},
        ]

    def _wire(self, mcp, monkeypatch, called):
        async def fake_list():
            return self._notebooks()

        monkeypatch.setattr("jupyter_mcp_spaces.spaces.list_notebooks", fake_list)

        @mcp.tool()
        async def use_notebook(notebook_name, notebook_path="", mode="connect", kernel_id=None):
            """Upstream: opens a notebook by path."""
            called["path"] = notebook_path
            return "opened"

        from jupyter_mcp_spaces.extension import _wrap_use_notebook

        _wrap_use_notebook(mcp)
        return mcp._tool_manager._tools["use_notebook"].fn

    @pytest.mark.asyncio
    async def test_a_display_name_becomes_a_uid(self, monkeypatch):
        called = {}
        fn = self._wire(MCPServer("t"), monkeypatch, called)
        await fn(notebook_name="nb", notebook_path="Sales forecast")
        assert called["path"] == "ntb-2"

    @pytest.mark.asyncio
    async def test_the_file_name_works_too(self, monkeypatch):
        called = {}
        fn = self._wire(MCPServer("t"), monkeypatch, called)
        await fn(notebook_name="nb", notebook_path="welcome_to_datalayer")
        assert called["path"] == "ntb-1"

    @pytest.mark.asyncio
    async def test_a_uid_is_passed_straight_through(self, monkeypatch):
        # Already an identifier: resolving it again would be a wasted call.
        called = {}
        fn = self._wire(MCPServer("t"), monkeypatch, called)
        await fn(notebook_name="nb", notebook_path="ntb-3")
        assert called["path"] == "ntb-3"

    @pytest.mark.asyncio
    async def test_an_ambiguous_name_asks_rather_than_opens(self, monkeypatch):
        called = {}
        fn = self._wire(MCPServer("t"), monkeypatch, called)
        with pytest.raises(ValueError) as caught:
            await fn(notebook_name="nb", notebook_path="Sales")
        assert "2 notebooks match" in str(caught.value)
        # And nothing was opened.
        assert "path" not in called

    @pytest.mark.asyncio
    async def test_an_unknown_name_says_so(self, monkeypatch):
        called = {}
        fn = self._wire(MCPServer("t"), monkeypatch, called)
        with pytest.raises(ValueError) as caught:
            await fn(notebook_name="nb", notebook_path="nothing like this")
        assert "list_notebooks" in str(caught.value)

    @pytest.mark.asyncio
    async def test_creating_does_not_resolve(self, monkeypatch):
        # A notebook being created does not exist yet, so there is nothing to
        # match and the name given is the name wanted.
        called = {}
        fn = self._wire(MCPServer("t"), monkeypatch, called)
        await fn(notebook_name="nb", notebook_path="brand new.ipynb", mode="create")
        assert called["path"] == "brand new.ipynb"
