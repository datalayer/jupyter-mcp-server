# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""One extension building on another, without reaching into its insides.

Extensions register in name order, and that ordering exists for exactly one
reason: so an extension can narrow or extend a tool an earlier one already
put on the server. Doing that means reaching the extension being built on and
the state it keeps — and until these two accessors existed the only route was
`manager._extensions` and `extension._manager`, two private attributes in
somebody else's package. Code that reaches that way works until the day this
package stores things differently, and then breaks downstream.

Launch the tests:
```
$ pytest tests/test_extensions_compose.py -v
```
"""

from __future__ import annotations

from typing import Any

from reactor import PluginCompatibility, PluginManifest

from jupyter_mcp_sandboxes.extension import SandboxesExtension
from jupyter_mcp_server.extensions import ExtensionManager, JupyterMCPExtension


class _Named(JupyterMCPExtension):
    def __init__(self, name: str) -> None:
        self._name = name

    def manifest(self) -> Any:
        return PluginManifest(
            name=self._name,
            version="0.0.1",
            description="A registered extension",
            author="Tests",
            compatibility=PluginCompatibility(api_version="v1"),
        )


def test_a_registered_extension_is_reachable_by_its_manifest_name():
    manager = ExtensionManager()
    first = _Named("alpha")
    manager.register(first)
    manager.register(_Named("beta"))
    assert manager.get("alpha") is first


def test_an_extension_that_is_not_installed_is_none_rather_than_an_error():
    """Not installed is a configuration, not a failure.

    The caller degrades — leaving its tool off the list — and a server that
    raised here would refuse to start because an optional package was absent.
    """
    assert ExtensionManager().get("not-installed") is None


def test_the_sandboxes_extension_publishes_the_registry_its_tools_write_to():
    """The same object, not an equal one.

    A downstream tool acting on its own manager would be a second set of
    sandboxes under the same names, where "the active one" means two
    different things depending on which tool you asked.
    """
    extension = SandboxesExtension()
    assert extension.sandboxes is extension._manager


def test_the_sandboxes_extension_is_found_under_the_name_it_publishes():
    """The lookup and the manifest have to agree.

    A downstream extension asks for a string. If that string is not the one
    the manifest declares, `get` answers None, the tool is quietly left off
    the list, and nothing anywhere says why.
    """
    manager = ExtensionManager()
    extension = SandboxesExtension()
    manager.register(extension)
    assert manager.get(extension.manifest().name) is extension


class TestAnExtensionFromAnotherHost:
    """The entry-point group is `reactor.mcp.extensions`, not this server's own.

    So an extension written against `reactor_mcp_server.McpExtension` — with
    none of this server's hooks — is a legitimate thing to find on it. Refusing
    it would make the shared group a private one in all but name.
    """

    @staticmethod
    def _generic():
        from reactor import PluginManifest
        from reactor_mcp_server import McpExtension, tool

        class Generic(McpExtension):
            def manifest(self):
                return PluginManifest(name="generic", version="1.0.0")

            @tool()
            async def from_elsewhere(self) -> str:
                """A tool that knows nothing about Jupyter."""
                return "ok"

        return Generic()

    def test_its_tools_are_collected(self):
        from jupyter_mcp_server.extensions import ExtensionManager

        manager = ExtensionManager()
        manager.register(self._generic())
        manager._discovered = True

        assert [spec.name for spec in manager.tools()] == ["from_elsewhere"]

    def test_the_jupyter_hooks_it_does_not_have_are_not_demanded(self):
        """Asked for by name, so an extension without them has none rather
        than breaking the sandbox factory for everybody else."""
        import logging
        from types import SimpleNamespace

        from jupyter_mcp_server.extensions import ExtensionManager

        manager = ExtensionManager()
        manager.register(self._generic())
        manager._discovered = True

        assert manager.create_code_sandbox(SimpleNamespace(), logging.getLogger("t")) is None

    def test_something_that_is_not_an_extension_at_all_is_refused(self):
        import pytest

        from jupyter_mcp_server.extensions import ExtensionManager

        with pytest.raises(TypeError):
            ExtensionManager().register(object())
