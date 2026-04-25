# Copyright (c) 2025-2026 Datalayer, Inc.
# Distributed under the terms of the Modified BSD License.

SHELL := /bin/bash

.PHONY: help install start start-noauth start-noauth-agent clean

JUPYTER_PORT ?= 8888
MCP_PORT ?= 4040
JUPYTER_TOKEN ?= MY_TOKEN
MCP_TOKEN ?= MY_MCP_TOKEN
DOCUMENT_ID ?= notebook.ipynb
MODEL ?= bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0
ROOT_DIR ?= ../../dev/content

BEDROCK_ENV = \
	AWS_ACCESS_KEY_ID=$${DATALAYER_BEDROCK_AWS_ACCESS_KEY_ID} \
	AWS_SECRET_ACCESS_KEY=$${DATALAYER_BEDROCK_AWS_SECRET_ACCESS_KEY} \
	AWS_DEFAULT_REGION=$${DATALAYER_BEDROCK_AWS_DEFAULT_REGION}

JUPYTER_URL := http://127.0.0.1:$(JUPYTER_PORT)
MCP_URL := http://127.0.0.1:$(MCP_PORT)/mcp
MCP_HEALTH_URL := http://127.0.0.1:$(MCP_PORT)/api/healthz

help:
	@echo "Jupyter MCP Server CLI Example"
	@echo ""
	@echo "Targets:"
	@echo "  install  - Install example dependencies"
	@echo "  start    - Start JupyterLab, MCP server, and pydantic-ai CLI"
	@echo "  start-noauth - Start everything with --insecure-mcp-noauth (local dev only)"
	@echo "  start-noauth-agent - Run only the CLI against an existing no-auth MCP endpoint"
	@echo "  clean    - Remove local logs"
	@echo ""
	@echo "Important variables (override with VAR=value make start):"
	@echo "  MODEL=$(MODEL)"
	@echo "  JUPYTER_PORT=$(JUPYTER_PORT)"
	@echo "  MCP_PORT=$(MCP_PORT)"
	@echo "  JUPYTER_TOKEN=$(JUPYTER_TOKEN)"
	@echo "  MCP_TOKEN=$(MCP_TOKEN)"
	@echo "  DOCUMENT_ID=$(DOCUMENT_ID)"

install:
	pip install -e ../..
	pip install 'pydantic-ai[mcp]' jupyterlab==4.4.1 jupyter-collaboration==4.0.2 'jupyter-mcp-tools>=0.1.4' ipykernel pycrdt

start:
	@set -euo pipefail; \
	JUPYTER_PID=""; \
	MCP_PID=""; \
	cleanup() { \
		echo ""; \
		echo "Stopping background services..."; \
		if [[ -n "$$MCP_PID" ]]; then kill "$$MCP_PID" 2>/dev/null || true; fi; \
		if [[ -n "$$JUPYTER_PID" ]]; then kill "$$JUPYTER_PID" 2>/dev/null || true; fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	echo "Starting JupyterLab at $(JUPYTER_URL)/lab ..."; \
	jupyter lab \
		--port $(JUPYTER_PORT) \
		--ip 0.0.0.0 \
		--ServerApp.port_retries 0 \
		--IdentityProvider.token $(JUPYTER_TOKEN) \
		--ServerApp.root_dir $(ROOT_DIR) \
		> .jupyter.log 2>&1 & \
	JUPYTER_PID=$$!; \
	echo "Waiting for JupyterLab health endpoint..."; \
	until curl -fsS "$(JUPYTER_URL)/api?token=$(JUPYTER_TOKEN)" >/dev/null 2>&1; do sleep 1; done; \
	echo "Starting Jupyter MCP Server at $(MCP_URL) ..."; \
	jupyter-mcp-server start \
		--transport streamable-http \
		--jupyter-url $(JUPYTER_URL) \
		--jupyter-token $(JUPYTER_TOKEN) \
		--document-id $(DOCUMENT_ID) \
		--start-new-runtime true \
		--mcp-token $(MCP_TOKEN) \
		--port $(MCP_PORT) \
		> .mcp.log 2>&1 & \
	MCP_PID=$$!; \
	echo "Waiting for Jupyter MCP Server health endpoint..."; \
	until curl -fsS "$(MCP_HEALTH_URL)" >/dev/null 2>&1; do sleep 1; done; \
	echo ""; \
	echo "JupyterLab: $(JUPYTER_URL)/lab?token=$(JUPYTER_TOKEN)"; \
	echo "MCP endpoint: $(MCP_URL)"; \
	echo "Running pydantic-ai CLI with model: $(MODEL)"; \
	echo ""; \
	$(BEDROCK_ENV) \
	PYDANTIC_AI_MODEL="$(MODEL)" \
	JUPYTER_MCP_URL="$(MCP_URL)" \
	MCP_TOKEN="$(MCP_TOKEN)" \
	python agent.py

start-noauth:
	@set -euo pipefail; \
	JUPYTER_PID=""; \
	MCP_PID=""; \
	cleanup() { \
		echo ""; \
		echo "Stopping background services..."; \
		if [[ -n "$$MCP_PID" ]]; then kill "$$MCP_PID" 2>/dev/null || true; fi; \
		if [[ -n "$$JUPYTER_PID" ]]; then kill "$$JUPYTER_PID" 2>/dev/null || true; fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	echo "Starting JupyterLab at $(JUPYTER_URL)/lab ..."; \
	jupyter lab \
		--port $(JUPYTER_PORT) \
		--ip 0.0.0.0 \
		--ServerApp.port_retries 0 \
		--IdentityProvider.token $(JUPYTER_TOKEN) \
		--ServerApp.root_dir $(ROOT_DIR) \
		> .jupyter.log 2>&1 & \
	JUPYTER_PID=$$!; \
	echo "Waiting for JupyterLab health endpoint..."; \
	until curl -fsS "$(JUPYTER_URL)/api?token=$(JUPYTER_TOKEN)" >/dev/null 2>&1; do sleep 1; done; \
	echo "Starting Jupyter MCP Server at $(MCP_URL) without MCP auth..."; \
	jupyter-mcp-server start \
		--transport streamable-http \
		--jupyter-url $(JUPYTER_URL) \
		--jupyter-token $(JUPYTER_TOKEN) \
		--document-id $(DOCUMENT_ID) \
		--start-new-runtime true \
		--insecure-mcp-noauth \
		--port $(MCP_PORT) \
		> .mcp.log 2>&1 & \
	MCP_PID=$$!; \
	echo "Waiting for Jupyter MCP Server health endpoint..."; \
	until curl -fsS "$(MCP_HEALTH_URL)" >/dev/null 2>&1; do sleep 1; done; \
	echo ""; \
	echo "WARNING: MCP endpoint auth is disabled (local dev only)."; \
	echo "JupyterLab: $(JUPYTER_URL)/lab?token=$(JUPYTER_TOKEN)"; \
	echo "MCP endpoint: $(MCP_URL)"; \
	echo "Running pydantic-ai CLI with model: $(MODEL)"; \
	echo ""; \
	$(BEDROCK_ENV) \
	PYDANTIC_AI_MODEL="$(MODEL)" \
	JUPYTER_MCP_URL="$(MCP_URL)" \
	MCP_TOKEN="" \
	python agent.py

start-noauth-agent:
	@set -euo pipefail; \
	echo "Checking MCP health endpoint (no auth): $(MCP_HEALTH_URL)"; \
	curl -fsS "$(MCP_HEALTH_URL)" >/dev/null; \
	echo "MCP endpoint is reachable."; \
	echo "Running pydantic-ai CLI with model: $(MODEL)"; \
	echo ""; \
	$(BEDROCK_ENV) \
	PYDANTIC_AI_MODEL="$(MODEL)" \
	JUPYTER_MCP_URL="$(MCP_URL)" \
	MCP_TOKEN="" \
	python agent.py

clean:
	rm -f .jupyter.log .mcp.log