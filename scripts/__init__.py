# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Repository scripts, importable so their tests can run.

`tests/test_mcpb_version_sync.py` imports `scripts.sync_mcpb_version`, and
without this file that import fails at collection — so the test that exists
to catch version drift between `__version__.py` and the mcpb manifest has
never run. A test that cannot be collected is worse than no test: the suite
is green and the thing it guards is unguarded.
"""
