# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) 2023-2026 Datalayer, Inc.
# BSD 3-Clause License

"""Telling a client that what it holds is still current.

The failure to avoid is the one where *not modified* and *nothing* look the
same. A client that read an empty result as an empty notebook would show
somebody no cells at all, so the answer says so in a named field rather than
by being empty.

Launch the tests:
```
$ pytest tests/test_revalidation.py -v
```
"""

from __future__ import annotations

import pytest
from mcp.types import CallToolRequestParams, CallToolResult, TextContent

from jupyter_mcp_server.results import CACHE_META_KEY, answer, etag_for
from jupyter_mcp_server.revalidation import (
    NOT_MODIFIED_KEY,
    REVALIDATION_EXTENSION,
    RevalidationExtension,
    answered_etag,
    requested_etag,
)


def holding(etag: str = "", name: str = "read_notebook") -> CallToolRequestParams:
    meta = {CACHE_META_KEY: {"etag": etag}} if etag else None
    return CallToolRequestParams(name=name, arguments={}, _meta=meta)


def read(value: dict, **overrides) -> CallToolResult:
    fields = {"kind": "notebook.read", "ttl_ms": 5000, "etag": True}
    fields.update(overrides)
    return answer(value, **fields)


@pytest.fixture
def extension() -> RevalidationExtension:
    return RevalidationExtension()


async def served(extension, params, result):
    async def call_next(ctx):
        return result

    return await extension.intercept_tool_call(params, object(), call_next)


class TestReadingTheVersions:
    def test_a_client_that_holds_nothing_says_nothing(self):
        assert requested_etag(holding()) == ""

    def test_a_tool_that_stamps_nothing_answers_nothing(self):
        assert answered_etag(answer("hi", kind="cell.read")) == ""

    def test_a_read_carries_a_version(self):
        assert answered_etag(read({"cells": [1]})).startswith('W/"')

    def test_the_same_answer_has_the_same_version(self):
        assert answered_etag(read({"cells": [1]})) == answered_etag(read({"cells": [1]}))

    def test_a_changed_answer_has_a_different_one(self):
        assert answered_etag(read({"cells": [1]})) != answered_etag(read({"cells": [2]}))

    def test_the_version_is_weak(self):
        """It says *this means the same thing*, not *this is byte-for-byte
        what you had* — the answer is assembled per call."""
        assert etag_for({"a": 1}).startswith('W/"')


@pytest.mark.asyncio
class TestRevalidating:
    async def test_a_matching_version_answers_not_modified(self, extension):
        result = read({"cells": [1, 2]})
        served_back = await served(extension, holding(answered_etag(result)), result)
        block = served_back.meta[CACHE_META_KEY]
        assert block[NOT_MODIFIED_KEY] is True
        assert served_back.content == []
        assert served_back.structured_content is None

    async def test_not_modified_says_so_rather_than_being_empty(self, extension):
        """A client that read an empty result as an empty notebook would show
        somebody no cells at all."""
        result = read({"cells": [1, 2]})
        served_back = await served(extension, holding(answered_etag(result)), result)
        assert NOT_MODIFIED_KEY in served_back.meta[CACHE_META_KEY]

    async def test_not_modified_carries_the_hints_again(self, extension):
        """So holding it for another window costs nothing."""
        result = read({"cells": [1]})
        etag = answered_etag(result)
        block = (await served(extension, holding(etag), result)).meta[CACHE_META_KEY]
        assert block["ttlMs"] == 5000 and block["etag"] == etag
        assert block["cacheScope"] == "private"

    async def test_a_different_version_answers_the_whole_thing(self, extension):
        result = read({"cells": [1, 2]})
        served_back = await served(extension, holding('W/"something-else"'), result)
        assert served_back is result

    async def test_a_client_holding_nothing_gets_the_whole_thing(self, extension):
        result = read({"cells": [1, 2]})
        assert await served(extension, holding(), result) is result

    async def test_an_unstamped_tool_and_an_empty_client_do_not_match(self, extension):
        """Both are the empty string, and comparing them equal would answer
        "unchanged" on a first call about something the client has never
        seen. The most likely way to get this wrong, and invisible from
        either side alone."""
        result = answer({"cells": [1]}, kind="cell.read")
        assert await served(extension, holding(), result) is result

    async def test_a_tool_that_stamps_no_version_is_never_revalidated(self, extension):
        """Answering "unchanged" about something nobody is tracking is worse
        than answering it again."""
        result = answer({"cells": [1]}, kind="cell.read")
        assert await served(extension, holding('W/"anything"'), result) is result

    async def test_an_error_is_never_turned_into_not_modified(self, extension):
        """A client that treated a refusal as its cached answer being current
        would go on using a result the server has just declined to confirm."""
        result = read({"cells": [1]})
        etag = answered_etag(result)
        failed = CallToolResult(
            content=[TextContent(type="text", text="no")],
            is_error=True,
            meta=result.meta,
        )
        assert await served(extension, holding(etag), failed) is failed

    async def test_the_tool_still_runs(self, extension):
        """This saves bandwidth, not work: the version comes from what the
        tool answered, so there is no way to know it is unchanged without
        producing it. Stating it in a test so nobody optimises on a promise
        this does not make."""
        ran = []

        async def call_next(ctx):
            ran.append(1)
            return read({"cells": [1]})

        result = read({"cells": [1]})
        await extension.intercept_tool_call(
            holding(answered_etag(result)), object(), call_next
        )
        assert ran == [1]


def test_the_extension_identifier_is_one_constant():
    assert RevalidationExtension.identifier == REVALIDATION_EXTENSION


def test_the_settings_name_the_field_a_client_reads():
    assert RevalidationExtension().settings()["notModifiedKey"] == NOT_MODIFIED_KEY
