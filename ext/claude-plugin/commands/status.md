<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

---
description: Show the Datalayer connection, notebooks and sandboxes
---

Report the state of the Datalayer connection, briefly.

Steps:

1. Call `list_notebooks` and say how many notebooks this account can reach,
   and which one is active.
2. Call `list_kernels` and report which code sandboxes are running.
3. If any call is refused for want of a scope, say exactly which scope is
   missing and that re-authorizing from Datalayer settings widens it — do not
   retry the call.

Keep it to a few lines. This is a status check, not a report.
