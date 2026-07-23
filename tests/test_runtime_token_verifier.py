# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""
Unit tests for RuntimeTokenVerifier (jupyter_mcp_server.server): no server needed,
imports directly from the server module.

Launch the tests:
```
$ pytest tests/test_runtime_token_verifier.py -v
```
"""

import hmac
from unittest.mock import patch

import pytest

from jupyter_mcp_server.server import RuntimeTokenVerifier


class TestRuntimeTokenVerifier:
    """verify_token() must accept the configured token, reject anything else,
    and do the comparison in constant time (CWE-208: timing side-channel via `!=`)."""

    @pytest.mark.asyncio
    async def test_accepts_matching_token(self):
        verifier = RuntimeTokenVerifier("secret-token")

        access_token = await verifier.verify_token("secret-token")

        assert access_token is not None
        assert access_token.token == "secret-token"

    @pytest.mark.asyncio
    async def test_rejects_mismatched_token(self):
        verifier = RuntimeTokenVerifier("secret-token")

        assert await verifier.verify_token("wrong-token") is None

    @pytest.mark.asyncio
    async def test_rejects_wrong_length_token(self):
        verifier = RuntimeTokenVerifier("secret-token")

        assert await verifier.verify_token("s") is None

    @pytest.mark.asyncio
    async def test_comparison_is_constant_time(self):
        """Guards against regressing to a plain `!=`, which leaks byte-position
        timing information on the configured token (CWE-208)."""
        verifier = RuntimeTokenVerifier("secret-token")

        target = "jupyter_mcp_server.server.hmac.compare_digest"
        with patch(target, wraps=hmac.compare_digest) as spy:
            await verifier.verify_token("wrong-token")

        spy.assert_called_once_with("wrong-token", "secret-token")
