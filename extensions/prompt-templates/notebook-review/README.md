<!--
  ~ Copyright (c) 2024- Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

## 🧪 Overview

This template guides an agent through a careful, evidence-based review of a Jupyter Notebook. It is for understanding execution order, dependencies, notebook context, hidden state, and reproducibility before proposing changes.

Use it when you want an auditable review of a notebook without immediately running cells, installing dependencies, or editing content.

## 💡 How to Use

1. Read [`AGENT.md`](AGENT.md).
1. Copy its contents into your MCP client's system prompt or project agent instructions.
1. Ask the agent to review the notebook and name the notebook or the questions you want answered.
1. Review the evidence-backed findings and the affected-cell summary.
1. Explicitly approve any execution, dependency installation, or notebook edit before the agent performs it.

## 🎯 What the Template Reviews

- The intended execution order and whether a cell relies on earlier setup.
- Imports, variables, files, data sources, and other dependencies.
- Context that may be missing from the selected notebook or cell range.
- Hidden kernel state, stale outputs, and reproducibility risks.
- The evidence supporting each finding, including the relevant cells or outputs.

______________________________________________________________________

- **Version**: 1.0.0
- **Author**: Jupyter MCP Server Community
- **Last Update**: 2026-09-07
