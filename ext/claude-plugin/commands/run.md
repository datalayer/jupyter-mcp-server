<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

---
description: Run a cell, or the whole notebook, on Datalayer
argument-hint: [cell index, "all", or a description]
---

Execute code in the Datalayer notebook we are working in.

Execution happens on the server, so it keeps running whether or not this
session stays open. Say so when a computation looks long.

Steps:

1. If no notebook is active, run `/datalayer:notebook` first.
2. Work out what `$ARGUMENTS` means:
   - a number — execute that cell with `execute_cell`;
   - `all` — read the notebook, then execute the code cells in order;
   - anything else — find the cell that matches the description, show it, and
     confirm before running it.
3. Report what each cell produced. If a cell fails, show the error and offer a
   fix rather than retrying blindly.

Never edit a cell to make it pass without saying what you changed and why.
