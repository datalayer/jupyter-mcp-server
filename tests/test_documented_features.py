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
