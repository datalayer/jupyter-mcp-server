# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Where a deployment substitutes its own behaviour for this server's.

This package is the scaffolding: the protocol surface, the tools against a
plain Jupyter server, and the mechanisms. What a *deployment* does with those
mechanisms is its own — and the seams here are how it says so, in the shape
this package already uses for the audit sink, the token verifier and the task
store: an environment variable naming a class.

Two exist for the subscription work, and each answers a real problem rather
than a hypothetical one.

`JUPYTER_MCP_PUBLISHER_CLASS` — the SDK's bus reaches clients attached to
*this process*. That is the whole story for a server somebody runs on their
laptop and no story at all behind several replicas, where a client attached
to one never hears an edit made through another.

`JUPYTER_MCP_RESOURCE_GATE_CLASS` — a deployment that addresses notebooks by
its own identifiers serves its own resources and does not want these:
`notebook://{name}` is the name a *worker* knows, and its clients have never
seen one.

Both default to the behaviour that makes this server work unconfigured,
because a server that needs configuration to serve resources is a server that
does not work out of the box.

Launch the tests:
```
$ pytest tests/test_extension_seams.py -v
```
"""

from __future__ import annotations

import pytest

from jupyter_mcp_server import notifications, resources


@pytest.fixture(autouse=True)
def _clean():
    """No seam configured, whatever a previous test did."""
    notifications.use_publisher(None)
    resources.use_gate(None)
    yield
    notifications.use_publisher(None)
    resources.use_gate(None)


class TestTheDefaultsNeedNoConfiguration:
    def test_no_publisher_is_configured_by_default(self):
        assert notifications.resolve_publisher() is None

    def test_every_resource_is_served_by_default(self):
        for template in (
            resources.NOTEBOOK_RESOURCE,
            resources.CELL_RESOURCE,
            resources.OUTPUT_RESOURCE,
        ):
            assert resources.serves(template) is True


@pytest.mark.asyncio
class TestSubstitutingThePublisher:
    async def test_a_configured_publisher_gets_the_event(self):
        sent = []

        class _Publisher:
            async def publish(self, uri):
                sent.append(uri)
                return True

        notifications.use_publisher(_Publisher())
        assert await notifications.publish_notebook_updated(object(), "work") is True
        assert sent == ["notebook://work"]

    async def test_the_in_process_bus_is_not_also_used(self):
        """A deployment that has a publisher is one where this process is not
        where the subscribers are. Publishing to both would send half the
        event twice."""
        published = []

        class _Bus:
            async def publish(self, event):
                published.append(event)

        class _Server:
            def __init__(self):
                handler = type("H", (), {"_bus": _Bus()})()
                entry = type("E", (), {"handler": handler})()
                self._lowlevel_server = type(
                    "L", (), {"_request_handlers": {"subscriptions/listen": entry}}
                )()

        class _Publisher:
            async def publish(self, uri):
                return True

        notifications.use_publisher(_Publisher())
        await notifications.publish_notebook_updated(_Server(), "work")
        assert published == []

    async def test_a_failing_publisher_never_fails_the_edit(self):
        class _Publisher:
            async def publish(self, uri):
                raise RuntimeError("the queue is gone")

        notifications.use_publisher(_Publisher())
        assert await notifications.publish_notebook_updated(object(), "work") is False


class TestSubstitutingTheResourceGate:
    def test_a_gate_can_withhold_a_resource(self):
        class _Gate:
            def serves(self, uri):
                return "outputs" not in uri

        resources.use_gate(_Gate())
        assert resources.serves(resources.NOTEBOOK_RESOURCE) is True
        assert resources.serves(resources.OUTPUT_RESOURCE) is False

    def test_a_gate_that_cannot_decide_serves(self):
        """The safe direction for a *scaffold*: a broken gate leaves the
        server answering, rather than silently serving nothing and looking
        like a server with no resources."""

        class _Gate:
            def serves(self, uri):
                raise RuntimeError("no idea")

        resources.use_gate(_Gate())
        assert resources.serves(resources.NOTEBOOK_RESOURCE) is True

    def test_withholding_is_not_the_same_as_not_found(self):
        """"We do not answer this here" and "there is no such cell" are
        different answers. A client told the second when the first is true
        goes looking for a cell it will never find."""
        assert not issubclass(resources.ResourceWithheld, resources.ResourceNotFound)
        assert not issubclass(resources.ResourceNotFound, resources.ResourceWithheld)


class TestTheResourcesActuallyAsk:
    """A gate nothing consults is a setting that does nothing."""

    @staticmethod
    def _server_source() -> str:
        import inspect

        from jupyter_mcp_server import server

        return inspect.getsource(server)

    @pytest.mark.parametrize(
        "template",
        ["NOTEBOOK_RESOURCE", "CELL_RESOURCE", "OUTPUT_RESOURCE"],
    )
    def test_each_resource_asks_the_gate(self, template):
        assert f"resources.serves(resources.{template})" in self._server_source()

    def test_it_asks_before_reading_the_notebook(self):
        """Reading first would make a withheld resource cost a round trip to
        the document server before refusing."""
        source = self._server_source()
        assert source.index("resources.serves(resources.NOTEBOOK_RESOURCE)") < source.index(
            "await resources.read_notebook(notebook_manager, name)"
        )


class TestTheSeamsLookLikeTheOnesAlreadyHere:
    """One shape for every hook, so a deployment learns it once."""

    def test_both_are_named_by_an_environment_variable(self):
        assert notifications.PUBLISHER_CLASS_ENV.startswith("JUPYTER_MCP_")
        assert resources.RESOURCE_GATE_CLASS_ENV.startswith("JUPYTER_MCP_")

    def test_a_class_that_cannot_be_imported_is_fatal(self, monkeypatch):
        """The audit sink's rule, for the audit sink's reason: a deployment
        that configured this and got a server running without it believes
        something is happening that is not."""
        monkeypatch.setenv(notifications.PUBLISHER_CLASS_ENV, "no.such.module.Thing")
        notifications.use_publisher(None)
        notifications._publisher_resolved = False
        with pytest.raises(RuntimeError):
            notifications.resolve_publisher()

    def test_a_class_of_the_wrong_shape_is_fatal(self, monkeypatch):
        monkeypatch.setenv(resources.RESOURCE_GATE_CLASS_ENV, "builtins.object")
        resources.use_gate(None)
        resources._gate_resolved = False
        with pytest.raises(RuntimeError):
            resources.resolve_gate()
