"""Map every MCP-registered name in the checkout to the file that defines it.

Reads each module and takes the name of every function actually decorated
with @mcp.tool / @mcp.prompt (MCPServer registers under the function
name when no name= override is given; this repo uses none). Output feeds
build_pages.mjs so each generated page carries a source link.

Deliberately records the file but not the line number: line numbers move on
every unrelated edit, and .github/workflows/docs.yml fails the build on any
difference between the checked-in generation and a fresh one.

    python gen_sourcemap.py <src-root> <out.json>
"""
import ast
import json
import os
import sys

SRC, OUT = sys.argv[1], sys.argv[2]

# Directories that never hold canonical sources. "build" and "dist" matter in
# particular: `pip install ./ext/sandboxes` leaves a setuptools copy of the
# extension at ext/sandboxes/build/lib/..., and scanning it would map the
# sandbox tools to a build artifact instead of the real file.
#: Extensions whose tools are registered conditionally, and so are absent from
#: a default snapshot.
#:
#: The reference documents the server as it runs out of the box: a Jupyter
#: backend, with the tools that implies. `jupyter-mcp-spaces` only registers
#: when the server is pointed at Datalayer, and it *hides* `list_files`,
#: `list_kernels` and `connect_to_jupyter` when it does — so no single snapshot
#: can contain both sets, and including these here would make the reference
#: permanently stale against itself. They are documented with the extension
#: that provides them.
CONDITIONAL_EXTENSIONS = {"spaces"}

SKIP_DIRS = {
    ".git", ".tox", ".venv", ".eggs", "__pycache__", "build", "dist",
    "docs", "node_modules", "site-packages", "tests", "venv",
}


def decorated_functions(source: str):
    """Every function this module decorates with `@mcp.tool` / `@mcp.prompt`.

    Parsed rather than matched. A regex for the decorator finds it in prose
    too — a docstring saying "applied under `@mcp.tool`" reads as a
    registration, and the next `def` after it gets indexed as a tool that does
    not exist. That is not hypothetical: `results.py` describes the decorator
    it wraps, and the scanner indexed its inner `decorate` function.

    Reading the syntax tree also means a decorator split across lines, or one
    inside an `if`, is found without a window to scan forward through.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(call, ast.Attribute)
                and isinstance(call.value, ast.Name)
                and call.value.id == "mcp"
                and call.attr in ("tool", "prompt")
            ):
                yield call.attr, node.name
                break



entries = {}
for base, dirs, files in os.walk(SRC):
    # Prune in place so os.walk never descends into them.
    if os.path.basename(base) == "ext":
        dirs[:] = [d for d in dirs if d not in CONDITIONAL_EXTENSIONS]
    dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
    files = sorted(files)
    for fn in files:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(base, fn)
        rel = os.path.relpath(path, SRC).replace("\\", "/")
        source = open(path, encoding="utf-8", errors="replace").read()
        try:
            found = list(decorated_functions(source))
        except SyntaxError as error:
            # A file this interpreter cannot parse is a file whose tools
            # cannot be indexed. Saying so beats silently documenting fewer
            # tools than the server has.
            raise SystemExit(f"{rel} could not be parsed: {error}") from error
        for kind, name in found:
            prev = entries.get(name)
            if prev and prev["file"] != rel:
                # Fail loudly rather than let os.walk order pick a winner.
                # Two causes: a stale build tree holding a second copy, or an
                # extension registering a name the core server already uses.
                # An extension that does that on purpose — replacing a tool
                # rather than adding one — belongs in CONDITIONAL_EXTENSIONS,
                # so the reference documents one of them and not a
                # contradiction.
                raise SystemExit(
                    f"{name} is registered in two files: "
                    f"{prev['file']} and {rel}. Remove the stray copy "
                    "(a stale build/ tree?), or list the extension in "
                    "CONDITIONAL_EXTENSIONS if it replaces the tool "
                    "deliberately, and re-run."
                )
            entries[name] = {"kind": kind, "file": rel}

# Sorted so the output is byte-stable whatever order os.walk yields.
entries = dict(sorted(entries.items()))
with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(entries, fh, indent=1)
    fh.write("\n")
print(f"{len(entries)} entries -> {OUT}")
for name, e in entries.items():
    print(f"  {e['kind']:6} {name:28} {e['file']}")
