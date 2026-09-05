# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""A subscribed client hears that a notebook changed.

One worker serves one user, and that user may have several agents. So this is
the ordinary case rather than an exotic one: agent A edits a cell, agent B is
subscribed to the notebook, and B finds out — same process, no polling.

The channel is the SDK's. At 2026-07-28 a client opens `subscriptions/listen`
naming the URIs it cares about, and the SDK acknowledges, filters and
streams; it even ships the bus. What was missing was anybody publishing onto
it.

Worth stating because the obvious reading of "implement subscriptions" is to
write `resources/subscribe`, and on the modern wire the SDK *ignores* that
handler: `get_capabilities` derives the capability from whether
`subscriptions/listen` is served.

Launch the tests:
```
$ pytest tests/test_notebook_update_notifications.py -v
```
"""

from __future__ import annotations

import pytest

from jupyter_mcp_server import notifications


class _FakeSession:
    """A stand-in for a `ServerSession`.

    A class rather than `object()`, because the registry holds sessions
    weakly and a bare `object()` cannot be weakly referenced — which is not a
    property of anything real, only of the placeholder.
    """

    async def send_resource_updated(self, uri):
        return None


class _Bus:
    """A bus that remembers, standing in for the SDK's."""

    def __init__(self, explode: bool = False) -> None:
        self.published: list = []
        self._explode = explode

    async def publish(self, event) -> None:
        if self._explode:
            raise RuntimeError("the stream is gone")
        self.published.append(event)


class _Server:
    def __init__(self, bus=None) -> None:
        handler = type("H", (), {"_bus": bus})()
        entry = type("E", (), {"handler": handler})()
        self._lowlevel_server = type(
            "L", (), {"_request_handlers": {"subscriptions/listen": entry}}
        )()


class TestWhichNotebookChanged:
    def test_the_tool_s_own_argument_wins(self):
        assert notifications.target_notebook({"notebook_name": "other"}, lambda: "current") == "other"

    def test_the_activated_notebook_otherwise(self):
        assert notifications.target_notebook({}, lambda: "current") == "current"

    def test_a_blank_argument_is_not_a_name(self):
        """A subscriber told the *wrong* notebook changed is worse than one
        told nothing: it refetches the wrong document and believes it is
        current."""
        assert notifications.target_notebook({"notebook_name": "  "}, lambda: "current") == "current"

    def test_no_current_notebook_is_no_name_rather_than_a_crash(self):
        def boom():
            raise RuntimeError("none open")

        assert notifications.target_notebook({}, boom) == ""


@pytest.mark.asyncio
class TestPublishing:
    async def test_a_subscriber_is_told_the_notebook_uri(self):
        bus = _Bus()
        assert await notifications.publish_notebook_updated(_Server(bus), "work") is True
        assert [event.uri for event in bus.published] == ["notebook://work"]

    async def test_the_uri_is_the_one_the_resource_is_read_at(self):
        """A subscriber matches on the URI it subscribed to. A different
        spelling here is an event the SDK filters out, and nothing anywhere
        says so — the client simply never hears."""
        from jupyter_mcp_server import resources

        assert notifications.notebook_uri("work") == resources.NOTEBOOK_RESOURCE.replace(
            "{name}", "work"
        )

    async def test_nothing_is_published_for_no_notebook(self):
        bus = _Bus()
        assert await notifications.publish_notebook_updated(_Server(bus), "") is False
        assert bus.published == []

    async def test_a_server_with_no_stream_is_not_an_error(self):
        """An older SDK, or a server built without the listen handler."""
        assert await notifications.publish_notebook_updated(_Server(None), "work") is False

    async def test_a_failing_bus_never_fails_the_edit(self):
        """It runs after the tool has done its work and returned. Failing the
        edit because the news about the edit would not go out trades the work
        for the story about the work."""
        assert await notifications.publish_notebook_updated(_Server(_Bus(explode=True)), "work") is False


class TestWhichCallsAnnounce:
    """The set is declared as what *mutates*, not as "not the readers"."""

    def test_the_writing_tools_are_in_it(self):
        for kind in ("cell.edit", "cell.insert", "cell.delete", "cell.execute"):
            assert kind in notifications.MUTATING_KINDS

    def test_the_reading_tools_are_not(self):
        """A reader that published would wake every subscriber on every read,
        and a subscriber that refetches on every read is a polling loop with
        extra steps."""
        for kind in ("cell.read", "notebook.read", "notebooks.list", "kernels.list"):
            assert kind not in notifications.MUTATING_KINDS

    def test_every_kind_named_here_is_a_kind_the_server_declares(self):
        """A typo publishes nothing and looks like a decision. Held against
        the `@structured` decorators rather than a second list."""
        import pathlib
        import re

        import jupyter_mcp_server

        root = pathlib.Path(jupyter_mcp_server.__file__).parent
        declared = set()
        for path in root.rglob("*.py"):
            declared.update(re.findall(r'@structured\(\s*"([^"]+)"', path.read_text()))
        assert declared, "no @structured kinds found; the search stopped working"
        assert notifications.MUTATING_KINDS <= declared, (
            notifications.MUTATING_KINDS - declared
        )

    def test_every_cell_writing_kind_the_server_declares_is_named(self):
        """The direction that goes silently wrong: a new writing tool missing
        from the set publishes nothing, and a subscriber never learns."""
        import pathlib
        import re

        import jupyter_mcp_server

        root = pathlib.Path(jupyter_mcp_server.__file__).parent
        declared = set()
        for path in root.rglob("*.py"):
            declared.update(re.findall(r'@structured\(\s*"([^"]+)"', path.read_text()))
        writing = {
            kind
            for kind in declared
            if kind.startswith("cell.")
            and not kind.endswith(".read")
        }
        assert writing <= notifications.MUTATING_KINDS, writing - notifications.MUTATING_KINDS


class TestTheDecoratorActuallyAnnounces:
    """A publisher nothing calls tells nobody anything.

    The recurring shape here: `register_interrupt` was defined, tested and
    called by nothing for as long as it existed. So the call site is asserted
    as well as the function.
    """

    def test_the_result_wrapper_publishes(self):
        import inspect

        from jupyter_mcp_server import results

        assert "MUTATING_KINDS" in inspect.getsource(results.structured)
        assert "publish_notebook_updated(" in inspect.getsource(results._announce)

    def test_it_publishes_after_the_call_and_not_before(self):
        """A subscriber told a cell changed before it did refetches the old
        document and caches it as new."""
        import inspect

        from jupyter_mcp_server import results

        source = inspect.getsource(results.structured)
        assert source.index("await wrapper(") < source.index("_announce(")


class TestTheOlderWayToAsk:
    """`resources/subscribe`, which is how a 2025-11-25 client asks.

    Registered even though the modern wire cannot dispatch it, because this
    server answers both eras and most clients today are on the older one.
    Registering it is also what makes `resources.subscribe` true in the
    2025-11-25 handshake — the SDK derives that capability from whether the
    handler exists — and it is what takes `resources-subscribe` and
    `resources-unsubscribe` out of the conformance baseline.
    """

    def test_both_methods_are_served(self):
        from jupyter_mcp_server.server import mcp

        handlers = mcp._lowlevel_server._request_handlers
        assert "resources/subscribe" in handlers
        assert "resources/unsubscribe" in handlers

    def test_the_older_handshake_now_offers_subscription(self):
        from mcp.server.lowlevel.server import NotificationOptions

        from jupyter_mcp_server.server import mcp

        capabilities = mcp._lowlevel_server.get_capabilities(
            NotificationOptions(), {}, protocol_version="2025-11-25"
        )
        assert capabilities.resources.subscribe is True

    def test_a_session_hears_about_what_it_subscribed_to(self):
        session = _FakeSession()
        notifications.legacy_subscribe(session, "notebook://work")
        try:
            assert session in notifications.legacy_subscribers("notebook://work")
        finally:
            notifications.legacy_unsubscribe(session, "notebook://work")

    def test_a_session_hears_nothing_about_anything_else(self):
        session = _FakeSession()
        notifications.legacy_subscribe(session, "notebook://work")
        try:
            assert notifications.legacy_subscribers("notebook://other") == []
        finally:
            notifications.legacy_unsubscribe(session, "notebook://work")

    def test_unsubscribing_stops_it(self):
        session = _FakeSession()
        notifications.legacy_subscribe(session, "notebook://work")
        notifications.legacy_unsubscribe(session, "notebook://work")
        assert notifications.legacy_subscribers("notebook://work") == []

    def test_unsubscribing_from_something_never_subscribed_is_not_an_error(self):
        """The client's intent — stop telling me about this — is satisfied
        either way, and refusing it teaches a client to retry something that
        is already true."""
        notifications.legacy_unsubscribe(_FakeSession(), "notebook://never")

    def test_a_subscription_outlives_the_request_that_made_it(self):
        """The whole point, and what was broken until 2026-09-05.

        The map was weak-keyed, so that a session going away took its
        subscriptions with it. Nothing else holds a `ServerSession`: the
        subscription was collected between the request that made it and the
        next call, every time, and the server told nobody while reporting
        that it had published. Nothing here could see it, because every test
        held the session in a local variable.
        """
        import gc

        class _Session:
            pass

        notifications.legacy_subscribe(_Session(), "notebook://ghost")
        gc.collect()
        assert notifications.legacy_subscribers("notebook://ghost")

    def test_unsubscribing_from_the_last_uri_lets_the_session_go(self):
        """The map holds sessions now, so what removes them has to be said:
        a session with nothing left to hear is one to let go of."""
        session = object()
        notifications.legacy_subscribe(session, "notebook://one")
        notifications.legacy_unsubscribe(session, "notebook://one")
        assert session not in notifications._LEGACY

    def test_the_registry_has_a_ceiling(self):
        """A client that subscribes and vanishes without unsubscribing costs
        one entry until the next publish, not a leak without a ceiling."""
        for index in range(notifications.MAX_SUBSCRIBED_SESSIONS + 10):
            notifications.legacy_subscribe(object(), f"notebook://{index}")
        assert len(notifications._LEGACY) <= notifications.MAX_SUBSCRIBED_SESSIONS


@pytest.mark.asyncio
class TestBothErasAreTold:
    """Both halves run, because both eras can be connected at once.

    This server answers 2026-07-28 and 2025-11-25, and a client on each is
    two clients. Sending only on the wire the last subscriber used would
    leave the other silent — a bug that appears only when two are connected.
    """

    async def test_a_legacy_subscriber_is_told(self):
        told = []

        class _Session:
            async def send_resource_updated(self, uri):
                told.append(uri)

        session = _Session()
        notifications.legacy_subscribe(session, "notebook://work")
        try:
            await notifications.publish_notebook_updated(_Server(_Bus()), "work")
        finally:
            notifications.legacy_unsubscribe(session, "notebook://work")
        assert told == ["notebook://work"]

    async def test_a_legacy_subscriber_is_told_by_a_server_with_no_bus(self):
        """The two halves are independent, and the legacy one used to be
        reached only through the modern one: `publish` returned early when
        the server had no `subscriptions/listen`, so an SDK without that
        stream told its 2025-11-25 subscribers nothing — which is every
        subscriber such a server has."""
        told = []

        class _Session:
            async def send_resource_updated(self, uri):
                told.append(uri)

        class _NoBus:
            """A server the bus cannot be reached through."""

        session = _Session()
        notifications.legacy_subscribe(session, "notebook://work")
        try:
            assert await notifications.publish_notebook_updated(_NoBus(), "work") is True
        finally:
            notifications.legacy_unsubscribe(session, "notebook://work")
        assert told == ["notebook://work"]

    async def test_the_bus_is_told_as_well(self):
        bus = _Bus()

        class _Session:
            async def send_resource_updated(self, uri):
                return None

        session = _Session()
        notifications.legacy_subscribe(session, "notebook://work")
        try:
            await notifications.publish_notebook_updated(_Server(bus), "work")
        finally:
            notifications.legacy_unsubscribe(session, "notebook://work")
        assert [event.uri for event in bus.published] == ["notebook://work"]

    async def test_a_dead_session_is_dropped_rather_than_retried_for_ever(self):
        class _Session:
            async def send_resource_updated(self, uri):
                raise RuntimeError("gone")

        session = _Session()
        notifications.legacy_subscribe(session, "notebook://work")
        await notifications.publish_notebook_updated(_Server(_Bus()), "work")
        assert notifications.legacy_subscribers("notebook://work") == []


class TestThePageSaysWhatHappens:
    """Two claims a reader would act on, held against the code."""

    @staticmethod
    def _page() -> str:
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "docs"
            / "docs"
            / "architecture"
            / "resources"
            / "index.mdx"
        )
        if not path.is_file():
            pytest.skip("the resources page is not here")
        return path.read_text()

    def test_it_says_the_event_carries_the_notebook_uri(self):
        page = self._page()
        assert "`notebook://{name}` in" in page
        assert notifications.notebook_uri("x") == "notebook://x"

    def test_it_still_says_another_party_is_not_covered(self):
        """A negative claim: nothing about adding a persistent observer later
        makes anybody re-read the paragraph explaining its absence."""
        assert "A change by somebody else is not covered" in self._page()


class TestOneTestsSubscriptionsAreNotAnothers:
    """The registry holds its sessions strongly, so a test that subscribes
    would leave the subscription behind for every test after it — in this
    file and in any other — and a suite that passes in one order would fail
    in another. `conftest` gives each test the registry it started with;
    these two run in this order and prove it.
    """

    def test_this_one_subscribes_and_walks_away(self):
        notifications.legacy_subscribe(object(), "notebook://left-behind")
        assert notifications.legacy_subscribers("notebook://left-behind")

    def test_and_this_one_finds_nothing_of_it(self):
        assert notifications.legacy_subscribers("notebook://left-behind") == []
