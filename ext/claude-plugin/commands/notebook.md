---
description: Open a Datalayer notebook and work in it
argument-hint: [notebook name or path]
---

Connect to a Datalayer notebook and make it the one we work in.

Steps:

1. Call `list_notebooks` to see what this account can reach.
2. If `$ARGUMENTS` is empty, show the list and ask which notebook to open.
   Otherwise pick the notebook whose name or path best matches
   `$ARGUMENTS`; if several match, list the candidates and ask rather than
   guessing.
3. Call `use_notebook` with a short, stable alias and the notebook's path.
4. Call `read_notebook` with the brief format and summarise what the notebook
   contains — how many cells, what it appears to be about, and where its last
   execution stopped.

Do not create a notebook unless you were asked to. If nothing matches, say so
and list what is available.
