"""Map every MCP-registered name in the checkout to the file that defines it.

Scans for @mcp.tool / @mcp.prompt decorators and takes the name of the first
`def`/`async def` after each decorator (FastMCP registers under the function
name when no name= override is given; this repo uses none). Output feeds
build_pages.mjs so each generated page carries a source link.

Deliberately records the file but not the line number: line numbers move on
every unrelated edit, and .github/workflows/docs.yml fails the build on any
difference between the checked-in generation and a fresh one.

    python gen_sourcemap.py <src-root> <out.json>
"""
import json
import os
import re
import sys

SRC, OUT = sys.argv[1], sys.argv[2]
DECOR = re.compile(r"@mcp\.(tool|prompt)\b")
DEF = re.compile(r"\s*(?:async\s+)?def\s+(\w+)")

entries = {}
for base, _dirs, files in os.walk(SRC):
    if any(seg in base for seg in (".git", "node_modules", "__pycache__", "tests")):
        continue
    for fn in files:
        if not fn.endswith(".py"):
            continue
        path = os.path.join(base, fn)
        rel = os.path.relpath(path, SRC).replace("\\", "/")
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
        for i, line in enumerate(lines):
            m = DECOR.search(line)
            if not m:
                continue
            kind = m.group(1)
            # find the def after the decorator (skip decorator args/other decorators)
            for j in range(i + 1, min(i + 40, len(lines))):
                d = DEF.match(lines[j])
                if d:
                    name = d.group(1)
                    entries[name] = {"kind": kind, "file": rel}
                    break

# Sorted so the output is byte-stable whatever order os.walk yields.
entries = dict(sorted(entries.items()))
with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(entries, fh, indent=1)
    fh.write("\n")
print(f"{len(entries)} entries -> {OUT}")
for name, e in entries.items():
    print(f"  {e['kind']:6} {name:28} {e['file']}")
