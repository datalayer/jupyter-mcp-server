---
name: code-review
description: Review a change to Jupyter MCP Server. Use when reviewing a pull request or a diff in this repository — it covers the failure modes this codebase actually produces, the contracts that hold the docs and the protocol to the code, and the result-shape rules a new tool has to follow.
---

# Reviewing a change to Jupyter MCP Server

This server is what an agent talks to when it reads and runs somebody's
notebooks. Most of what goes wrong here is quiet: a test that passes without
exercising its subject, a tool that answers an empty list instead of an
error, a page that documents a flag nothing reads. None of it fails loudly,
and all of it has happened.

Review for those first. Ordinary bugs are usually caught by the suite.

## Start here: does the test exercise its subject?

The most common defect in this repository is not broken code — it is a test
that passes for a reason other than the one it claims. Two real examples:

- `test_an_expired_task_is_gone…` called `store.get()` before `store.list()`.
  `get()` deletes the expired record itself, so by the time `list()` ran there
  was nothing left to sweep and the sweep never executed. `list()` was
  iterating a dictionary while popping from it — a guaranteed `RuntimeError`
  — and the test named after that path was green.
- `tests/test_mcpb_version_sync.py` never ran at all. It imports
  `scripts.sync_mcpb_version`, `scripts/` had no `__init__.py`, and the module
  failed at collection. The suite was green and the version drift it guards
  was unguarded.

So for every new or changed test, ask:

- **Would it fail if the behaviour were removed?** If you cannot say yes,
  delete the assertion or strengthen it. Say so in the review.
- **Does an earlier line already do the work?** A setup call that cleans up,
  caches, or short-circuits leaves the code under test unreached.
- **Does it assert a cell, or a substring of everything?** `assert "no" in
  output` passes on almost any English. Pull the row or the field apart.
- **Does it signal by raising inside a `try`?** Several functions here catch
  `Exception` deliberately — a test that raises to signal gets swallowed and
  asserts nothing. Record into a list and assert the list.
- **Does it set an environment variable that was already read at import?**
  `config`-style modules read once. Patch the attribute, not the environment.

## The quiet failure

The pattern to hunt for: a well-formed request, a truthful empty answer, and
a legitimate-looking zero. Nobody investigates a zero.

- A tool that answers `[]` where it could not reach the thing it was listing.
  An empty list is what a user with no notebooks looks like.
- An `except` that returns a default instead of raising. Ask what the caller
  will render, and whether they could tell that answer from a real one.
- A metric or a field that stops being written. A panel showing zero reads
  the same as a healthy system.
- Retention, sweeps and background jobs. "It ran and found nothing" and "it
  stopped running" must not look the same in a log.

An error the caller can act on beats an empty answer they will believe.

## Result shape and cache hints

Every tool answers through `@structured` in `jupyter_mcp_server/results.py`.
Check:

- The tool annotates its return type (`ToolAnswer`, `TableAnswer`,
  `OutputsAnswer`). Returning nothing advertises no output schema, and the
  generated reference silently loses its Output section.
- `shape=` matches what the body returns. A mapping is already the structured
  answer; rendering it under `result` hands a client text where it had an
  object, and nothing looks wrong until a field is read.
- **A cache hint needs a listing or an ETag.** `ttl_ms` on a read that cannot
  be revalidated hands an agent a stale notebook and no way to tell. Nothing
  that changes a notebook may be hinted at all. `tests/test_results.py`
  enforces this — if a change edits that test, ask why.
- `cacheScope` stays `private` unless the answer genuinely is the same for
  every caller. A shared cache holding one person's notebooks for another is
  the failure the field exists to prevent.

## Contracts that must not drift

These tests exist because nothing else connects the two ends, and a mismatch
fails silently:

- `tests/test_documented_features.py` — the docs pages against the code.
  A page naming an environment variable nothing reads, a method that does not
  exist, or a store method the protocol does not have sends somebody to a
  feature that silently does not turn on. When a change adds a config
  variable, a public helper or a protocol method, the page and this test move
  with it.
- `tests/test_conformance.py` with `tests/conformance-baseline.yaml` — the
  specification's own suite. A new failure blocks the release. A baseline
  entry is a debt with a name; adding one needs a reason in the review.

## Extensions

- Extensions register in **name order**, and the SDK keeps the **original**
  when a tool name is registered twice. An extension that means to replace a
  tool must remove it first, or the replacement silently does nothing.
- A new extension needs its entry point in `pyproject.toml` under
  `jupyter_mcp_server.extensions`, and its tests under
  `extensions/<name>/tests`.
- The extension identifier belongs in one constant. When a feature moves into
  the core protocol, that should be a rename in one place.

## Protocol and transport

- The Streamable HTTP transport is stateless by default and issues no
  `Mcp-Session-Id`. That is right for one process many people reach — each
  request runs in its own context and the identity middleware sees the caller
  of *that* request. It is wrong where one process serves one user.
  `JUPYTER_MCP_STATEFUL` chooses; a change that hard-codes either is a
  regression for the other.
- `_meta` keys are the protocol's (`io.modelcontextprotocol/*`) or this
  project's namespace. Never invent an unnamespaced one.
- Identity comes from the request, not from the process. A tool that reaches
  for a credential in the environment works in one deployment and acts as the
  wrong person in another.

## Style this repository keeps

- **No backwards compatibility shims.** A rename replaces; there is no alias,
  no deprecation period, no migration path. If a change adds one, ask.
- **Comments say why, not what.** A comment restating the line below it is
  noise; one explaining a decision that looks wrong is the point.
- **No dead defence.** A guard that cannot fire reads as a guarantee and is
  worse than nothing. If a check is unreachable, remove it and put the
  reasoning where the decision actually is.
- **`noqa` only for rules this repo enables.** `ruff` flags the rest as
  unused, and a `noqa` carrying prose hides its own explanation. Put the
  reasoning in an ordinary comment.

## Before approving

```bash
make test-mcp-server      # ~15 minutes; do not cancel
make test-extensions      # seconds
.github/workflows/lint.sh # ruff, mypy, mdformat, pyproject validation
```

A change that touches a documented feature also runs
`pytest tests/test_documented_features.py`, and one that touches the wire
runs `pytest tests/test_conformance.py`.

## Writing the review

Say what breaks and for whom. "This returns an empty list when Spacer is
unreachable, so an agent will tell the user they have no notebooks" is worth
more than "consider adding error handling".

Rank by what a reader would do about it. A confirmed defect first, a
weakened test second, style last — and if the only findings are style, say
the change looks correct before listing them.
