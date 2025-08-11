#!/usr/bin/env bash
# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

pip install -e ".[lint,typing]"
mypy --install-types --non-interactive .
ruff check .
mdformat --check *.md
pipx run 'validate-pyproject[all]' pyproject.toml
