#!/usr/bin/env python3
# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""The feature docs, held to what the server actually does.

A documentation page is a promise. A page naming an environment variable the
server no longer reads, a class path that no longer imports, or a capability
that was renamed is worse than no page: somebody follows it, gets no error,
and concludes the feature is broken.

These are cheap checks — names, defaults, spellings — but they are exactly the
things that rot silently, because nothing else in the test suite reads the
documentation.

```
$ pytest tests/test_documented_features.py -v
```
"""

import asyncio
import pathlib
import re

import pytest

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "docs"


def _page(*parts: str) -> str:
    path = DOCS.joinpath(*parts)
    if not path.is_file():
        pytest.skip(f"{path} is not in this checkout")
    return path.read_text()


class TestTheAuditPage:
    @pytest.fixture(scope="class")
    def page(self):
        return _page("operations", "audit", "index.mdx")

    def test_it_names_the_variable_the_server_reads(self, page):
        """Matched whole, not as a substring: `JUPYTER_MCP_AUDIT` is inside
        `JUPYTER_MCP_AUDIT_SINK_CLASS`, so a loose check passes for a
        renamed variable the page never mentions."""
        from jupyter_mcp_server.audit import AUDIT_SINK_CLASS_ENV

        assert re.search(rf"\b{re.escape(AUDIT_SINK_CLASS_ENV)}\b", page)

    def test_the_class_it_tells_you_to_subclass_exists(self, page):
        from jupyter_mcp_server import audit

        assert "AuditSink" in page
        assert hasattr(audit, "AuditSink")

    def test_the_method_it_tells_you_to_write_is_the_one_called(self, page):
        from jupyter_mcp_server.audit import AuditSink

        assert "on_event" in page
        assert callable(AuditSink().on_event)

    def test_the_error_line_it_says_to_alert_on_is_the_one_logged(self, page):
        """The page tells operators to alert on this text. If the log line
        moved, that alert would silently never fire again."""
        import inspect

        from jupyter_mcp_server import audit

        source = inspect.getsource(audit._Guarded.on_event)
        assert "the call was not recorded" in page
        assert "the call was not recorded" in source

    def test_it_says_the_sink_cannot_opt_into_being_fatal(self, page):
        from jupyter_mcp_server.audit import _Guarded

        assert "propagate_errors" in page
        assert _Guarded.propagate_errors is False

    def test_both_class_path_spellings_it_documents_work(self, page):
        from jupyter_mcp_server.audit import load_sink_class

        assert "package.module:ClassName" in page or "module:ClassName" in page
        assert load_sink_class("jupyter_mcp_server.audit:AuditSink").__name__ == "AuditSink"
        assert load_sink_class("jupyter_mcp_server.audit.AuditSink").__name__ == "AuditSink"


class TestTheCapabilitiesPage:
    @pytest.fixture(scope="class")
    def page(self):
        return _page("operations", "capabilities", "index.mdx")

    def test_every_capability_it_names_is_declared(self, page):
        """A page naming one that does not exist sends somebody to configure
        nothing."""
        from jupyter_mcp_server.capabilities import CapabilityRegistry

        declared = {capability.name for capability in CapabilityRegistry().all()}
        named = set(re.findall(r"`([a-z]+\.[a-z-]+)`", page)) & {
            name for name in declared
        } | {name for name in declared if f"`{name}`" in page}
        assert named == declared, f"documented {named}, declared {declared}"

    def test_it_names_the_environment_variable(self, page):
        from jupyter_mcp_server.capabilities import CAPABILITIES_ENV

        assert CAPABILITIES_ENV in page

    def test_it_names_the_extension_id_and_the_resource(self, page):
        from jupyter_mcp_server.capabilities import (
            CAPABILITIES_EXTENSION,
            CAPABILITIES_RESOURCE,
        )

        assert CAPABILITIES_EXTENSION in page
        assert CAPABILITIES_RESOURCE in page

    def test_the_default_it_documents_is_the_default(self, page):
        """The page says off by default, and that is the whole point of the
        capability."""
        from jupyter_mcp_server.capabilities import (
            KERNEL_AUTO_RESTART,
            CapabilityRegistry,
        )

        assert "Off by default" in page
        assert CapabilityRegistry().enabled(KERNEL_AUTO_RESTART) is False

    def test_the_off_spellings_it_lists_are_accepted(self, page):
        from jupyter_mcp_server.capabilities import parse_setting

        for spelling in ("off", "false", "0", "no", "disabled"):
            assert f"`{spelling}`" in page, spelling
            assert parse_setting(f"x={spelling}") == ("x", False)

    def test_the_advertised_shape_it_shows_is_the_shape(self, page):
        from jupyter_mcp_server.capabilities import get_capabilities, reset_capabilities

        reset_capabilities()
        try:
            advertised = get_capabilities().advertise()
        finally:
            reset_capabilities()
        for key in advertised:
            assert f'"{key}"' in page, f"the page does not show `{key}`"
        for key in ("name", "description", "enabled", "source"):
            assert f'"{key}"' in page, f"the page does not show a declared entry's `{key}`"

    def test_the_error_message_it_quotes_is_the_one_raised(self, page):
        """An operator reading the page and then meeting a different message
        has to work out for themselves whether it is the same thing.

        The message is *raised* rather than read out of the source: the
        function's own docstring names the capability too, so a source-text
        check passes even after the message has stopped naming it.
        """
        from jupyter_mcp_server.capabilities import reset_capabilities
        from jupyter_mcp_server.utils import KernelGoneError, ensure_code_sandbox_alive

        class _Dead:
            def is_alive(self):
                return False

        class _Manager:
            def get_code_sandbox(self, _name):
                return _Dead()

            def ensure_code_sandbox_alive(self, *_a, **_k):  # pragma: no cover
                return None

        reset_capabilities()
        with pytest.raises(KernelGoneError) as raised:
            asyncio.run(ensure_code_sandbox_alive(_Manager(), "nb", lambda: None))
        message = str(raised.value)
        for fragment in ("restart_notebook", "kernel.auto-restart"):
            assert fragment in page, f"the page does not mention {fragment}"
            assert fragment in message, f"the raised message does not mention {fragment}"


class TestTheIdentityPage:
    @pytest.fixture(scope="class")
    def page(self):
        return _page("security", "identity", "index.mdx")

    def test_it_names_the_variable_and_the_helper(self, page):
        from jupyter_mcp_server import identity

        assert identity.TOKEN_VERIFIER_CLASS_ENV in page
        assert "current_identity" in page
        assert callable(identity.current_identity)


class TestTheGeneratedReferenceFindsTheRealTools:
    """The reference is generated from the source, so its scanner is code too.

    It used to find `@mcp.tool` with a regex, which matches the decorator
    wherever it appears — including in prose. `results.py` describes the
    decorator it wraps, so the scanner read that sentence as a registration
    and indexed the next function, `decorate`, as a tool. The docs build then
    failed comparing its list against a live snapshot of the server, which of
    course had no such tool.

    A scanner that reads syntax cannot make that mistake, and these say so.
    """

    @staticmethod
    def _scan(source: str):
        import importlib.util
        import pathlib

        generator = (
            pathlib.Path(__file__).resolve().parents[1]
            / "docs" / "sourcey" / "gen_sourcemap.py"
        )
        if not generator.is_file():
            pytest.skip("the docs generator is not in this checkout")
        # Imported for its function only; running the module walks the tree.
        text = generator.read_text()
        namespace: dict = {}
        start = text.index("def decorated_functions(")
        end = text.index("\nentries = {}")
        exec("import ast\n" + text[start:end], namespace)  # noqa: S102
        return list(namespace["decorated_functions"](source))

    def test_a_decorator_named_in_prose_is_not_a_tool(self):
        """The bug, exactly."""
        source = '''
def structured(kind):
    """Applied under `@mcp.tool`, so the schema comes from the signature."""
    def decorate(function):
        return function
    return decorate
'''
        assert self._scan(source) == []

    def test_a_real_registration_is_found(self):
        source = '''
@mcp.tool()
async def read_cell(cell_index: int) -> str:
    """Read a cell."""
'''
        assert self._scan(source) == [("tool", "read_cell")]

    def test_a_prompt_is_found_and_named_as_one(self):
        source = '''
@mcp.prompt()
def jupyter_cite(cells: list) -> str:
    """Cite cells."""
'''
        assert self._scan(source) == [("prompt", "jupyter_cite")]

    def test_a_decorator_split_across_lines_is_found(self):
        """Which the line-window scan could miss entirely."""
        source = '''
@mcp.tool(
    annotations=ToolAnnotations(
        title="Read Cell",
    ),
    structured_output=False,
)
@with_hooks("read_cell")
async def read_cell() -> str:
    """Read."""
'''
        assert self._scan(source) == [("tool", "read_cell")]

    def test_a_resource_is_not_indexed_as_a_tool(self):
        """This server registers `capabilities://` with `@mcp.resource`. The
        reference counts tools and resources separately and checks its list
        against a live snapshot, so a resource counted as a tool fails the
        docs build the same way `decorate` did."""
        source = '''
@mcp.resource("capabilities://")
def capabilities_resource() -> dict:
    """What this server can do."""
'''
        assert self._scan(source) == []

    def test_the_real_capabilities_resource_is_not_in_the_reference(self):
        """The case above, against the actual file rather than a sample."""
        import pathlib as _pathlib

        server = _pathlib.Path(__file__).resolve().parents[1] / "jupyter_mcp_server" / "server.py"
        found = {name for _kind, name in self._scan(server.read_text())}
        assert "capabilities_resource" not in found

    def test_somebody_elses_tool_decorator_is_not_ours(self):
        """`other.tool` is not `mcp.tool`, and indexing it would document a
        tool this server does not serve."""
        source = '''
@other.tool()
def not_ours() -> str:
    """No."""
'''
        assert self._scan(source) == []
