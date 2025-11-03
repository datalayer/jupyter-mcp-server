<!--
  ~ Copyright (c) 2023-2024 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

## 📝 Overview

This is the **general-purpose** prompt template for Jupyter MCP Server. It provides foundational guidance and best practices for using Jupyter MCP Server across a wide variety of use cases. **If you're new to Jupyter MCP, start here!**

## 💡 Core Philosophy: Explorer, Not Builder

The agent's core concept is to be an **Explorer, not a Builder**. It treats user requests as scientific inquiries rather than simple engineering tasks.

To achieve this, the agent follows the **Introspective Exploration Loop**:

1.  **Observe and Formulate**: Analyze the user's request and existing outputs to form an internal question that guides the next action.
2.  **Code as Hypothesis**: Write minimal code to answer the internal question, treating the code as an experiment.
3.  **Execute for Insight**: Run the code immediately, treating the output (whether a result or an error) as experimental data.
4.  **Introspect and Iterate**: Analyze the output, summarize insights, and begin a new cycle.

## 🚀 User Guide: How to Customize the Agent

You can "fine-tune" the agent for your project's specific needs by modifying the `Custom Context` within `AGENT.md`.

Open `AGENT.md` and find the `# Context` section:

```markdown
# Context

{{Add your custom context here, like your package installation, preferred code style, etc.}}
```

Replace the `{{...}}` placeholder with your project-specific rules.

#### Example:

To make the agent prefer the `Polars` library and adhere to the `black` code style, you would modify it like this:

```markdown
# Context

- **Library Preference**: Prioritize using the `Polars` library for data manipulation instead of `Pandas`.
- **Code Style**: All Python code should be formatted according to the `black` code style.
- **Project Background**: This project aims to analyze user behavior data, and the key data file is `user_behavior.csv`.
```

---

- **Version**: 1.0.0
- **Author**: Jupyter MCP Server Community
- **Last Update**: 2025-11-01