# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Notebook, cell and output resources: what an agent may read rather than be sent.

Tools push. Everything a call produces comes back whether the agent wanted it
or not, so a cell that printed a megabyte spends a megabyte of the client's
context every time anybody reads it. Resources pull: the agent is told what
exists and reads the one thing it needs.

That is what the output resource is for, and why a cell lists its outputs
rather than inlining them.

Launch the tests:
```
$ pytest tests/test_notebook_resources.py -v
```
"""

from __future__ import annotations

import json

import pytest

from jupyter_mcp_server import resources
from jupyter_mcp_server.models import Cell, Notebook

STREAM = {"output_type": "stream", "name": "stdout", "text": "hello\n"}
IMAGE = {"output_type": "display_data", "data": {"image/png": "AAA", "text/plain": "<Figure>"}}
ERROR = {"output_type": "error", "ename": "ValueError", "evalue": "no", "traceback": ["a", "b"]}


def _notebook() -> Notebook:
    return Notebook(
        cells=[
            Cell(cell_type="code", source="print('hello')", id="c1", outputs=[STREAM, IMAGE]),
            Cell(cell_type="markdown", source="# Title", id="c2"),
        ]
    )


class TestFindingACell:
    def test_a_cell_is_found_by_its_id(self):
        index, cell = resources.find_cell(_notebook(), "c2")
        assert index == 1 and cell.cell_type == "markdown"

    def test_an_unknown_id_is_not_found_rather_than_the_first_cell(self):
        with pytest.raises(resources.ResourceNotFound):
            resources.find_cell(_notebook(), "nope")

    def test_the_message_says_an_index_is_not_an_id(self):
        """The mistake somebody will make, given every tool takes an index."""
        with pytest.raises(resources.ResourceNotFound) as refused:
            resources.find_cell(_notebook(), "0")
        assert "index is not an id" in str(refused.value)


class TestTheOutputsType:
    def test_a_stream_is_text(self):
        assert resources.output_mime(STREAM) == "text/plain"

    def test_an_image_is_an_image(self):
        """`text/plain` is the fallback every kernel attaches beside the real
        thing. Preferring it would read every figure as the words
        `<Figure>`, and the agent could not tell that is what happened."""
        assert resources.output_mime(IMAGE) == "image/png"

    def test_an_error_is_text(self):
        assert resources.output_mime(ERROR) == "text/plain"

    def test_something_unrecognisable_is_text_rather_than_a_guess(self):
        assert resources.output_mime({"output_type": "future_kind"}) == "text/plain"
        assert resources.output_mime("not a dict") == "text/plain"


class TestReadingAnOutput:
    def test_a_stream_is_its_text(self):
        assert resources.output_text(STREAM) == "hello\n"

    def test_a_stream_written_as_a_list_is_joined(self):
        """Kernels send either, and a client that got `['a', 'b']` back as a
        string would show the brackets."""
        assert resources.output_text(
            {"output_type": "stream", "text": ["a", "b"]}
        ) == "ab"

    def test_an_error_is_its_traceback(self):
        assert resources.output_text(ERROR) == "a\nb"

    def test_an_error_with_no_traceback_still_says_what_it_was(self):
        assert "ValueError: no" in resources.output_text(
            {"output_type": "error", "ename": "ValueError", "evalue": "no"}
        )

    def test_an_image_is_its_own_data_not_its_caption(self):
        assert resources.output_text(IMAGE) == "AAA"


class TestTheCellDocument:
    def test_it_is_json_a_program_can_read(self):
        """Not the tools' `=====Cell 3 | type: code=====` banner, which is for
        a person reading a transcript — an agent parsing it back into fields
        gets it wrong on the first cell whose source contains "Cell"."""
        document = json.loads(resources.cell_document("work", 0, _notebook()[0]))
        assert document["id"] == "c1"
        assert document["cell_type"] == "code"

    def test_outputs_are_listed_and_not_inlined(self):
        """The whole point. A cell that printed a megabyte would otherwise
        cost a megabyte to read, which is what these resources exist to
        avoid."""
        document = json.loads(resources.cell_document("work", 0, _notebook()[0]))
        assert [output["index"] for output in document["outputs"]] == [0, 1]
        assert "hello" not in json.dumps(document["outputs"])

    def test_each_output_carries_its_real_type_and_where_to_read_it(self):
        """The MIME type is here rather than on the read, because the SDK
        fixes a template's type at registration. An agent that needs to know
        what an output *is* before spending context on it reads it here."""
        document = json.loads(resources.cell_document("work", 0, _notebook()[0]))
        assert document["outputs"][1]["mimeType"] == "image/png"
        assert document["outputs"][1]["uri"] == "notebook://work/cells/c1/outputs/1"

    def test_the_uri_names_the_notebook_it_came_from(self):
        """It carried the literal `{name}` in the first version of this, which
        is a URI no client can resolve and every client would try."""
        document = json.loads(resources.cell_document("other", 0, _notebook()[0]))
        assert "{name}" not in json.dumps(document)
        assert document["outputs"][0]["uri"].startswith("notebook://other/")


class TestWhatIsRegistered:
    """The templates, the audiences and the cache hints, as a client sees them."""

    @pytest.fixture(scope="class")
    def templates(self):
        import asyncio

        from jupyter_mcp_server.server import mcp

        return {
            template.uri_template: template
            for template in asyncio.run(mcp.list_resource_templates())
        }

    def test_all_three_are_templates(self, templates):
        assert resources.NOTEBOOK_RESOURCE in templates
        assert resources.CELL_RESOURCE in templates
        assert resources.OUTPUT_RESOURCE in templates

    def test_the_scheme_is_provider_neutral(self, templates):
        """This server talks to a Jupyter server. A `datalayer://` URI here
        would be a hosted platform's identifier on a resource that has
        nothing to do with it."""
        for uri in templates:
            assert not uri.startswith("datalayer://")

    def test_a_notebook_is_addressed_by_name_not_by_path(self, templates):
        """A path contains slashes and cannot sit in one template segment
        without being encoded into something nobody can read."""
        assert "{name}" in resources.NOTEBOOK_RESOURCE
        assert "{path}" not in resources.NOTEBOOK_RESOURCE

    def test_a_cell_is_addressed_by_id_not_by_index(self, templates):
        """An index is a position in a document somebody else is editing."""
        assert "{cell_id}" in resources.CELL_RESOURCE
        assert "{cell_index}" not in resources.CELL_RESOURCE

    def test_an_output_is_for_the_assistant(self, templates):
        """A person reads outputs in their notebook, where they are rendered,
        not through a URI."""
        annotations = templates[resources.OUTPUT_RESOURCE].annotations
        assert annotations.audience == ["assistant"]

    def test_a_notebook_is_for_both(self, templates):
        annotations = templates[resources.NOTEBOOK_RESOURCE].annotations
        assert set(annotations.audience) == {"assistant", "user"}

    def test_every_one_is_cached_privately(self, templates):
        """A notebook is one caller's. A proxy that shared this answer would
        hand somebody else's work to whoever asked next."""
        from jupyter_mcp_server.results import CACHE_META_KEY, SCOPE_PRIVATE

        for uri in (resources.NOTEBOOK_RESOURCE, resources.CELL_RESOURCE, resources.OUTPUT_RESOURCE):
            block = (templates[uri].meta or {}).get(CACHE_META_KEY) or {}
            assert block.get("cacheScope") == SCOPE_PRIVATE, uri
            assert block.get("ttlMs", 0) > 0, uri

    def test_an_output_is_held_longer_than_the_notebook(self, templates):
        """It does not change: a re-run replaces a cell's outputs rather than
        editing one, and the new ones are at new positions."""
        assert resources.OUTPUT_TTL_MS > resources.NOTEBOOK_TTL_MS


class TestThePageSaysWhatTheCodeDoes:
    """The resources page makes four claims a reader would act on.

    Each is held against the code, in the style `test_documented_features`
    uses for the tasks page: a page that describes a URI scheme, a cache
    scope or a MIME rule the code does not follow is worse than no page,
    because somebody writes a client against it.
    """

    @pytest.fixture(scope="class")
    def page(self):
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

    def test_the_three_uris_it_shows_are_the_three_registered(self, page):
        for uri in (
            resources.NOTEBOOK_RESOURCE,
            resources.CELL_RESOURCE,
            resources.OUTPUT_RESOURCE,
        ):
            assert f"`{uri}`" in page, uri

    def test_the_ttls_it_quotes_are_the_ttls(self, page):
        assert f"{resources.NOTEBOOK_TTL_MS // 1000} seconds" in page
        assert resources.OUTPUT_TTL_MS == 60_000 and "a minute" in page

    def test_it_still_says_the_output_audience_is_the_assistant(self, page):
        """A negative-ish claim: the page tells a reader a person will not see
        these, and nothing about widening the audience makes anybody re-read
        the paragraph."""
        import asyncio

        from jupyter_mcp_server.server import mcp

        templates = {
            template.uri_template: template
            for template in asyncio.run(mcp.list_resource_templates())
        }
        assert templates[resources.OUTPUT_RESOURCE].annotations.audience == [
            "assistant"
        ]
        assert "audience is the **assistant** alone" in page

    def test_the_richest_type_rule_it_explains_is_the_rule(self, page):
        assert "preferring it would read every figure as" in page
        assert resources.output_mime(IMAGE) == "image/png"
