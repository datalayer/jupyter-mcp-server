# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""An `async def` test with no marker is a test that sometimes does not run.

`pytest-asyncio` runs in **strict** mode here — `pytest.ini` sets no
`asyncio_mode` — so a coroutine test it is not told to take is refused with
*"async def functions are not natively supported"*. What made that
intermittent rather than obvious is `pytest-tornasync`: it collects any
coroutine test it finds, it is installed in some environments as another
package's dependency, and nothing in this repository asks for it. Whichever
plugin claims a test first decides whether it runs.

So an unmarked async test passed alone and failed in a full run, and the set
of failures moved between runs of the same suite — twice in two days, in two
different files. Neither was a broken test: both were tests nobody had told
pytest how to run.

This holds the rule instead of relying on which plugin wins: every `async def
test_*` carries a marker, on itself, on its class, or on its module. A test
that does not is named here, at authoring time, rather than in whichever run
happens to collect it differently.

Launch the tests:
```
$ pytest tests/test_every_async_test_is_marked.py -v
```
"""

from __future__ import annotations

import ast
import pathlib

import pytest

#: Where this repository keeps its tests. `examples/` has its own
#: dependencies and its own runner (`make test-examples`), and is left alone
#: for the reason `pytest.ini` leaves it out of collection.
TEST_ROOTS = ("tests", "extensions")

#: Directories that hold somebody else's code or a build product.
SKIP = {"node_modules", "build", "dist", ".conformance", "venv", "attic", ".git"}


def _repository() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def _marks_asyncio(decorators) -> bool:
    return any("asyncio" in ast.unparse(decorator) for decorator in decorators)


def _module_marks_asyncio(tree: ast.Module) -> bool:
    """A module-level `pytestmark = pytest.mark.asyncio` marks everything."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(getattr(target, "id", "") == "pytestmark" for target in node.targets):
            if "asyncio" in ast.unparse(node.value):
                return True
    return False


def _unmarked_in(path: pathlib.Path) -> list[str]:
    """Every async test in this file that nothing marks."""
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: list[str] = []

    def walk(body, inherited: bool) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, inherited or _marks_asyncio(node.decorator_list))
            elif isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
                if not inherited and not _marks_asyncio(node.decorator_list):
                    found.append(f"{node.name} (line {node.lineno})")

    walk(tree.body, _module_marks_asyncio(tree))
    return found


def _test_files() -> list[pathlib.Path]:
    repository = _repository()
    files: list[pathlib.Path] = []
    for root in TEST_ROOTS:
        for path in sorted((repository / root).rglob("test_*.py")):
            if SKIP.intersection(path.parts):
                continue
            files.append(path)
    return files


def test_every_async_test_carries_a_marker() -> None:
    repository = _repository()
    unmarked = [
        f"{path.relative_to(repository)}::{name}"
        for path in _test_files()
        for name in _unmarked_in(path)
    ]
    assert unmarked == [], (
        "async tests with no asyncio marker — they will be refused, or run "
        "only when another plugin happens to claim them first:\n  "
        + "\n  ".join(unmarked)
    )


def test_there_are_async_tests_to_check() -> None:
    """So a rewrite that moves the tests cannot make this pass by finding
    nothing to look at."""
    files = _test_files()
    assert len(files) > 20, files
    coroutines = sum(
        1
        for path in files
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")
    )
    assert coroutines > 50, coroutines


@pytest.mark.parametrize(
    "source, expected",
    [
        ("async def test_a(): ...", ["test_a (line 1)"]),
        ("import pytest\n@pytest.mark.asyncio\nasync def test_a(): ...", []),
        ("import pytest\npytestmark = pytest.mark.asyncio\nasync def test_a(): ...", []),
        (
            "import pytest\n@pytest.mark.asyncio\nclass TestX:\n    async def test_a(self): ...",
            [],
        ),
        ("class TestX:\n    async def test_a(self): ...", ["test_a (line 2)"]),
        ("def test_a(): ...", []),
        ("async def helper(): ...", []),
    ],
)
def test_the_rule_reads_each_shape(tmp_path, source, expected) -> None:
    """The three ways a test is marked, and the two ways it is not."""
    path = tmp_path / "test_sample.py"
    path.write_text(source)
    assert _unmarked_in(path) == expected
