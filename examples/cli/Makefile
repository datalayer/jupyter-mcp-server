# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

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
SANDBOX_VARIANT ?=
PYTHON ?= python

BEDROCK_ENV = \
	AWS_ACCESS_KEY_ID=$${DATALAYER_BEDROCK_AWS_ACCESS_KEY_ID:-$${AWS_ACCESS_KEY_ID}} \
	AWS_SECRET_ACCESS_KEY=$${DATALAYER_BEDROCK_AWS_SECRET_ACCESS_KEY:-$${AWS_SECRET_ACCESS_KEY}} \
	AWS_DEFAULT_REGION=$${DATALAYER_BEDROCK_AWS_DEFAULT_REGION:-$${AWS_DEFAULT_REGION}}

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
	@echo "  SANDBOX_VARIANT=$(SANDBOX_VARIANT)"

install:
	pip install -e ../..
	pip install 'pydantic-ai[mcp]' jupyterlab==4.4.1 jupyter-collaboration==4.0.2 'jupyter-mcp-tools>=0.1.4' ipykernel pycrdt

start:
	@set -euo pipefail; \
	VARIANT=""; \
	VARIANT_LABEL=""; \
	VARIANT_DESC=""; \
	JUPYTER_PID=""; \
	MCP_PID=""; \
	CLR_RESET="\033[0m"; \
	CLR_INFO="\033[1;34m"; \
	CLR_OK="\033[1;32m"; \
	CLR_WARN="\033[1;33m"; \
	CLR_STEP="\033[1;36m"; \
	log_info() { printf "%b\n" "$$CLR_INFO[info]$$CLR_RESET $$1"; }; \
	log_ok() { printf "%b\n" "$$CLR_OK[ok]$$CLR_RESET $$1"; }; \
	log_warn() { printf "%b\n" "$$CLR_WARN[warn]$$CLR_RESET $$1"; }; \
	log_step() { printf "%b\n" "$$CLR_STEP[step]$$CLR_RESET $$1"; }; \
	is_port_listening() { \
		local port="$$1"; \
		$(PYTHON) -c "import socket, sys; s=socket.socket(); s.settimeout(0.2); rc=s.connect_ex(('127.0.0.1', int(sys.argv[1]))); s.close(); sys.exit(0 if rc == 0 else 1)" "$$port" >/dev/null 2>&1; \
	}; \
	pick_random_free_port() { \
		local attempts="$$1"; \
		local i; \
		local port; \
		for ((i=1; i<=attempts; i++)); do \
			port="$$($(PYTHON) -c "import random; print(random.randint(20000, 65000))")"; \
			if ! is_port_listening "$$port"; then \
				echo "$$port"; \
				return 0; \
			fi; \
		done; \
		return 1; \
	}; \
	wait_for_health() { \
		local name="$$1"; \
		local url="$$2"; \
		local pid="$$3"; \
		local log_file="$$4"; \
		local timeout="$$5"; \
		local elapsed=0; \
		while ! curl -fsS "$$url" >/dev/null 2>&1; do \
			if [[ -n "$$pid" ]] && ! kill -0 "$$pid" 2>/dev/null; then \
				log_warn "$$name process exited before becoming healthy."; \
				if [[ -f "$$log_file" ]]; then \
					log_warn "Last lines from $$log_file:"; \
					tail -n 80 "$$log_file"; \
				fi; \
				return 1; \
			fi; \
			if (( elapsed >= timeout )); then \
				log_warn "Timed out waiting for $$name health endpoint ($$timeout s)."; \
				log_warn "Expected URL: $$url"; \
				if [[ -f "$$log_file" ]]; then \
					log_warn "Last lines from $$log_file:"; \
					tail -n 80 "$$log_file"; \
				fi; \
				return 1; \
			fi; \
			sleep 1; \
			elapsed=$$((elapsed + 1)); \
			if (( elapsed % 5 == 0 )); then \
				log_info "Still waiting for $$name... ($${elapsed}s/$${timeout}s)"; \
			fi; \
		done; \
		log_ok "$$name health endpoint is ready."; \
	}; \
	cleanup() { \
		echo ""; \
		log_warn "Stopping background services..."; \
		if [[ -n "$$MCP_PID" ]]; then kill "$$MCP_PID" 2>/dev/null || true; fi; \
		if [[ -n "$$JUPYTER_PID" ]]; then kill "$$JUPYTER_PID" 2>/dev/null || true; fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	log_info "A Jupyter server is always launched for this example."; \
	log_info "You can optionally add a sandbox backend on top of Jupyter."; \
	HAS_SANDBOX_EXT="false"; \
	if $(PYTHON) -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('jupyter_mcp_sandboxes') else 1)" >/dev/null 2>&1; then \
		HAS_SANDBOX_EXT="true"; \
	fi; \
	VARIANT="$${SANDBOX_VARIANT:-}"; \
	if [[ -z "$$VARIANT" ]]; then \
		if [[ "$$HAS_SANDBOX_EXT" == "true" && -t 0 ]]; then \
			echo ""; \
			log_step "Choose optional additional sandbox backend:"; \
			echo "  none (default), jupyterhub, datalayer, colab, kaggle, monty, modal, eval, docker"; \
			read -r -p "Variant [none]: " VARIANT; \
		else \
			VARIANT="none"; \
			if [[ "$$HAS_SANDBOX_EXT" != "true" ]]; then \
				log_warn "jupyter_mcp_sandboxes is not installed. Defaulting to additional sandbox: none."; \
			fi; \
		fi; \
	fi; \
	VARIANT="$${VARIANT:-none}"; \
	if [[ "$$HAS_SANDBOX_EXT" != "true" && "$$VARIANT" != "none" ]]; then \
		log_warn "jupyter_mcp_sandboxes is not installed. Forcing additional sandbox: none."; \
		VARIANT="none"; \
	fi; \
	case "$$VARIANT" in \
		none|jupyterhub|datalayer|colab|kaggle|monty|modal|eval|docker) ;; \
		*) echo "Invalid SANDBOX_VARIANT: $$VARIANT"; exit 1 ;; \
	esac; \
	if [[ "$$VARIANT" == "none" ]]; then \
		ENGINE="jupyter"; \
		VARIANT_LABEL="none"; \
		VARIANT_DESC="No additional sandbox. Code executes on the Jupyter kernel."; \
	elif [[ "$$VARIANT" == "jupyterhub" ]]; then \
		ENGINE="jupyter"; \
		VARIANT_LABEL="jupyterhub"; \
		VARIANT_DESC="Additional JupyterHub-backed runtime."; \
	else \
		ENGINE="$$VARIANT"; \
		VARIANT_LABEL="$$VARIANT"; \
		VARIANT_DESC="Additional sandbox runtime: $$VARIANT."; \
	fi; \
	check_variant_requirements() { \
		case "$$VARIANT" in \
			none) \
				;; \
			colab) \
				if [[ -z "$${RUNTIME_CHANNELS_URL:-}" && ( -z "$${RUNTIME_URL:-}" || -z "$${RUNTIME_ID:-}" || -z "$${RUNTIME_PROXY_TOKEN:-}" ) ]]; then \
					echo "Colab requires either RUNTIME_CHANNELS_URL, or RUNTIME_URL + RUNTIME_ID + RUNTIME_PROXY_TOKEN."; \
					echo "Examples:"; \
					echo "  SANDBOX_VARIANT=colab RUNTIME_CHANNELS_URL='wss://.../api/kernels/.../channels?...' make start"; \
					echo "  SANDBOX_VARIANT=colab RUNTIME_URL=... RUNTIME_ID=... RUNTIME_PROXY_TOKEN=... make start"; \
					exit 1; \
				fi; \
				;; \
			kaggle) \
				if [[ -n "$${RUNTIME_URL:-}" && -z "$${RUNTIME_ID:-}" && -z "$${RUNTIME_CHANNELS_URL:-}" && -z "$${KAGGLE_API_TOKEN:-}" && -z "$${RUNTIME_TOKEN:-}" ]]; then \
					echo "Kaggle interactive mode with RUNTIME_URL requires one of: RUNTIME_ID, RUNTIME_CHANNELS_URL, KAGGLE_API_TOKEN, or RUNTIME_TOKEN."; \
					echo "Examples:"; \
					echo "  SANDBOX_VARIANT=kaggle KAGGLE_API_TOKEN=... make start                # default batch mode"; \
					echo "  SANDBOX_VARIANT=kaggle KAGGLE_API_TOKEN=... SANDBOX_GPU=T4 make start # batch + accelerator"; \
					echo "  SANDBOX_VARIANT=kaggle RUNTIME_URL=... KAGGLE_API_TOKEN=... make start # interactive create"; \
					echo "  SANDBOX_VARIANT=kaggle RUNTIME_URL=... RUNTIME_ID=... make start       # interactive attach"; \
					exit 1; \
				fi; \
				;; \
			datalayer) \
				if [[ -z "$${RUNTIME_URL:-}" || -z "$${RUNTIME_TOKEN:-}" ]]; then \
					echo "Datalayer requires RUNTIME_URL and RUNTIME_TOKEN."; \
					echo "Example: SANDBOX_VARIANT=datalayer RUNTIME_URL=https://prod1.datalayer.run RUNTIME_TOKEN=... make start"; \
					exit 1; \
				fi; \
				;; \
			jupyterhub) \
				if [[ -z "$${RUNTIME_URL:-}" || -z "$${RUNTIME_TOKEN:-}" ]]; then \
					echo "JupyterHub requires RUNTIME_URL and RUNTIME_TOKEN (single-user server URL + API token)."; \
					echo "Example: SANDBOX_VARIANT=jupyterhub RUNTIME_URL=https://hub/user/<name> RUNTIME_TOKEN=... make start"; \
					exit 1; \
				fi; \
				;; \
			modal) \
				if [[ -z "$${MODAL_TOKEN_ID:-}" || -z "$${MODAL_TOKEN_SECRET:-}" ]]; then \
					if [[ ! -f "$${HOME}/.modal.toml" ]]; then \
						echo "Modal auth not found. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET or run: modal token new"; \
						exit 1; \
					fi; \
				fi; \
				;; \
			esac; \
	}; \
	check_variant_requirements; \
	JUPYTER_PORT_SELECTED="$$(pick_random_free_port 200)"; \
	if [[ -z "$$JUPYTER_PORT_SELECTED" ]]; then \
		log_warn "Could not find an available random Jupyter port after multiple attempts."; \
		exit 1; \
	fi; \
	JUPYTER_URL_RUNTIME="http://127.0.0.1:$$JUPYTER_PORT_SELECTED"; \
	MCP_PORT_SELECTED="$$(pick_random_free_port 200)"; \
	if [[ -z "$$MCP_PORT_SELECTED" ]]; then \
		log_warn "Could not find an available random MCP port after multiple attempts."; \
		exit 1; \
	fi; \
	MCP_URL_RUNTIME="http://127.0.0.1:$$MCP_PORT_SELECTED/mcp"; \
	MCP_HEALTH_URL_RUNTIME="http://127.0.0.1:$$MCP_PORT_SELECTED/api/healthz"; \
	log_ok "Base runtime: Jupyter server (always on)"; \
	log_ok "Additional sandbox: $$VARIANT_LABEL"; \
	log_info "$$VARIANT_DESC"; \
	log_info "Selected random Jupyter port: $$JUPYTER_PORT_SELECTED"; \
	log_info "Selected random MCP port: $$MCP_PORT_SELECTED"; \
	if [[ "$$VARIANT" != "none" ]]; then \
		log_info "MCP --sandbox-variant will be set to: $$ENGINE"; \
	fi; \
	log_step "Starting JupyterLab at $$JUPYTER_URL_RUNTIME/lab ..."; \
	jupyter lab \
		--port "$$JUPYTER_PORT_SELECTED" \
		--ip 0.0.0.0 \
		--ServerApp.port_retries 0 \
		--IdentityProvider.token $(JUPYTER_TOKEN) \
		--ServerApp.root_dir $(ROOT_DIR) \
		> .jupyter.log 2>&1 & \
	JUPYTER_PID=$$!; \
	log_step "Waiting for JupyterLab health endpoint..."; \
	wait_for_health "JupyterLab" "$$JUPYTER_URL_RUNTIME/api?token=$(JUPYTER_TOKEN)" "$$JUPYTER_PID" ".jupyter.log" 90; \
	log_step "Starting Jupyter MCP Server at $$MCP_URL_RUNTIME ..."; \
	jupyter-mcp-server start \
		--transport streamable-http \
		--sandbox-variant "$$ENGINE" \
		--jupyter-url "$$JUPYTER_URL_RUNTIME" \
		--jupyter-token $(JUPYTER_TOKEN) \
		--document-id $(DOCUMENT_ID) \
		--start-new-runtime true \
		--mcp-token $(MCP_TOKEN) \
		--port "$$MCP_PORT_SELECTED" \
		> .mcp.log 2>&1 & \
	MCP_PID=$$!; \
	log_step "Waiting for Jupyter MCP Server health endpoint..."; \
	wait_for_health "Jupyter MCP Server" "$$MCP_HEALTH_URL_RUNTIME" "$$MCP_PID" ".mcp.log" 90; \
	echo ""; \
	log_ok "JupyterLab: $$JUPYTER_URL_RUNTIME/lab?token=$(JUPYTER_TOKEN)"; \
	log_ok "MCP endpoint: $$MCP_URL_RUNTIME"; \
	log_ok "Additional sandbox: $$VARIANT_LABEL"; \
	log_step "Running pydantic-ai CLI with model: $(MODEL)"; \
	echo ""; \
	$(BEDROCK_ENV) \
	PYDANTIC_AI_MODEL="$(MODEL)" \
	JUPYTER_MCP_URL="$$MCP_URL_RUNTIME" \
	MCP_TOKEN="$(MCP_TOKEN)" \
	python agent.py

start-noauth:
	@set -euo pipefail; \
	VARIANT=""; \
	VARIANT_LABEL=""; \
	VARIANT_DESC=""; \
	JUPYTER_PID=""; \
	MCP_PID=""; \
	CLR_RESET="\033[0m"; \
	CLR_INFO="\033[1;34m"; \
	CLR_OK="\033[1;32m"; \
	CLR_WARN="\033[1;33m"; \
	CLR_STEP="\033[1;36m"; \
	log_info() { printf "%b\n" "$$CLR_INFO[info]$$CLR_RESET $$1"; }; \
	log_ok() { printf "%b\n" "$$CLR_OK[ok]$$CLR_RESET $$1"; }; \
	log_warn() { printf "%b\n" "$$CLR_WARN[warn]$$CLR_RESET $$1"; }; \
	log_step() { printf "%b\n" "$$CLR_STEP[step]$$CLR_RESET $$1"; }; \
	is_port_listening() { \
		local port="$$1"; \
		$(PYTHON) -c "import socket, sys; s=socket.socket(); s.settimeout(0.2); rc=s.connect_ex(('127.0.0.1', int(sys.argv[1]))); s.close(); sys.exit(0 if rc == 0 else 1)" "$$port" >/dev/null 2>&1; \
	}; \
	pick_random_free_port() { \
		local attempts="$$1"; \
		local i; \
		local port; \
		for ((i=1; i<=attempts; i++)); do \
			port="$$($(PYTHON) -c "import random; print(random.randint(20000, 65000))")"; \
			if ! is_port_listening "$$port"; then \
				echo "$$port"; \
				return 0; \
			fi; \
		done; \
		return 1; \
	}; \
	wait_for_health() { \
		local name="$$1"; \
		local url="$$2"; \
		local pid="$$3"; \
		local log_file="$$4"; \
		local timeout="$$5"; \
		local elapsed=0; \
		while ! curl -fsS "$$url" >/dev/null 2>&1; do \
			if [[ -n "$$pid" ]] && ! kill -0 "$$pid" 2>/dev/null; then \
				log_warn "$$name process exited before becoming healthy."; \
				if [[ -f "$$log_file" ]]; then \
					log_warn "Last lines from $$log_file:"; \
					tail -n 80 "$$log_file"; \
				fi; \
				return 1; \
			fi; \
			if (( elapsed >= timeout )); then \
				log_warn "Timed out waiting for $$name health endpoint ($$timeout s)."; \
				log_warn "Expected URL: $$url"; \
				if [[ -f "$$log_file" ]]; then \
					log_warn "Last lines from $$log_file:"; \
					tail -n 80 "$$log_file"; \
				fi; \
				return 1; \
			fi; \
			sleep 1; \
			elapsed=$$((elapsed + 1)); \
			if (( elapsed % 5 == 0 )); then \
				log_info "Still waiting for $$name... ($${elapsed}s/$${timeout}s)"; \
			fi; \
		done; \
		log_ok "$$name health endpoint is ready."; \
	}; \
	cleanup() { \
		echo ""; \
		log_warn "Stopping background services..."; \
		if [[ -n "$$MCP_PID" ]]; then kill "$$MCP_PID" 2>/dev/null || true; fi; \
		if [[ -n "$$JUPYTER_PID" ]]; then kill "$$JUPYTER_PID" 2>/dev/null || true; fi; \
	}; \
	trap cleanup EXIT INT TERM; \
	log_info "A Jupyter server is always launched for this example."; \
	log_info "You can optionally add a sandbox backend on top of Jupyter."; \
	HAS_SANDBOX_EXT="false"; \
	if $(PYTHON) -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('jupyter_mcp_sandboxes') else 1)" >/dev/null 2>&1; then \
		HAS_SANDBOX_EXT="true"; \
	fi; \
	VARIANT="$${SANDBOX_VARIANT:-}"; \
	if [[ -z "$$VARIANT" ]]; then \
		if [[ "$$HAS_SANDBOX_EXT" == "true" && -t 0 ]]; then \
			echo ""; \
			log_step "Choose optional additional sandbox backend:"; \
			echo "  none (default), jupyterhub, datalayer, colab, kaggle, monty, modal, eval, docker"; \
			read -r -p "Variant [none]: " VARIANT; \
		else \
			VARIANT="none"; \
			if [[ "$$HAS_SANDBOX_EXT" != "true" ]]; then \
				log_warn "jupyter_mcp_sandboxes is not installed. Defaulting to additional sandbox: none."; \
			fi; \
		fi; \
	fi; \
	VARIANT="$${VARIANT:-none}"; \
	if [[ "$$HAS_SANDBOX_EXT" != "true" && "$$VARIANT" != "none" ]]; then \
		log_warn "jupyter_mcp_sandboxes is not installed. Forcing additional sandbox: none."; \
		VARIANT="none"; \
	fi; \
	case "$$VARIANT" in \
		none|jupyterhub|datalayer|colab|kaggle|monty|modal|eval|docker) ;; \
		*) echo "Invalid SANDBOX_VARIANT: $$VARIANT"; exit 1 ;; \
	esac; \
	if [[ "$$VARIANT" == "none" ]]; then \
		ENGINE="jupyter"; \
		VARIANT_LABEL="none"; \
		VARIANT_DESC="No additional sandbox. Code executes on the Jupyter kernel."; \
	elif [[ "$$VARIANT" == "jupyterhub" ]]; then \
		ENGINE="jupyter"; \
		VARIANT_LABEL="jupyterhub"; \
		VARIANT_DESC="Additional JupyterHub-backed runtime."; \
	else \
		ENGINE="$$VARIANT"; \
		VARIANT_LABEL="$$VARIANT"; \
		VARIANT_DESC="Additional sandbox runtime: $$VARIANT."; \
	fi; \
	check_variant_requirements() { \
		case "$$VARIANT" in \
			none) \
				;; \
			colab) \
				if [[ -z "$${RUNTIME_CHANNELS_URL:-}" && ( -z "$${RUNTIME_URL:-}" || -z "$${RUNTIME_ID:-}" || -z "$${RUNTIME_PROXY_TOKEN:-}" ) ]]; then \
					echo "Colab requires either RUNTIME_CHANNELS_URL, or RUNTIME_URL + RUNTIME_ID + RUNTIME_PROXY_TOKEN."; \
					echo "Examples:"; \
					echo "  SANDBOX_VARIANT=colab RUNTIME_CHANNELS_URL='wss://.../api/kernels/.../channels?...' make start-noauth"; \
					echo "  SANDBOX_VARIANT=colab RUNTIME_URL=... RUNTIME_ID=... RUNTIME_PROXY_TOKEN=... make start-noauth"; \
					exit 1; \
				fi; \
				;; \
				kaggle) \
					if [[ -n "$${RUNTIME_URL:-}" && -z "$${RUNTIME_ID:-}" && -z "$${RUNTIME_CHANNELS_URL:-}" && -z "$${KAGGLE_API_TOKEN:-}" && -z "$${RUNTIME_TOKEN:-}" ]]; then \
						echo "Kaggle interactive mode with RUNTIME_URL requires one of: RUNTIME_ID, RUNTIME_CHANNELS_URL, KAGGLE_API_TOKEN, or RUNTIME_TOKEN."; \
						echo "Examples:"; \
						echo "  SANDBOX_VARIANT=kaggle KAGGLE_API_TOKEN=... make start-noauth                # default batch mode"; \
						echo "  SANDBOX_VARIANT=kaggle KAGGLE_API_TOKEN=... SANDBOX_GPU=T4 make start-noauth # batch + accelerator"; \
						echo "  SANDBOX_VARIANT=kaggle RUNTIME_URL=... KAGGLE_API_TOKEN=... make start-noauth # interactive create"; \
						echo "  SANDBOX_VARIANT=kaggle RUNTIME_URL=... RUNTIME_ID=... make start-noauth       # interactive attach"; \
						exit 1; \
					fi; \
					;; \
			datalayer) \
				if [[ -z "$${RUNTIME_URL:-}" || -z "$${RUNTIME_TOKEN:-}" ]]; then \
					echo "Datalayer requires RUNTIME_URL and RUNTIME_TOKEN."; \
					echo "Example: SANDBOX_VARIANT=datalayer RUNTIME_URL=https://prod1.datalayer.run RUNTIME_TOKEN=... make start-noauth"; \
					exit 1; \
				fi; \
				;; \
			jupyterhub) \
				if [[ -z "$${RUNTIME_URL:-}" || -z "$${RUNTIME_TOKEN:-}" ]]; then \
					echo "JupyterHub requires RUNTIME_URL and RUNTIME_TOKEN (single-user server URL + API token)."; \
					echo "Example: SANDBOX_VARIANT=jupyterhub RUNTIME_URL=https://hub/user/<name> RUNTIME_TOKEN=... make start-noauth"; \
					exit 1; \
				fi; \
				;; \
			modal) \
				if [[ -z "$${MODAL_TOKEN_ID:-}" || -z "$${MODAL_TOKEN_SECRET:-}" ]]; then \
					if [[ ! -f "$${HOME}/.modal.toml" ]]; then \
						echo "Modal auth not found. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET or run: modal token new"; \
						exit 1; \
					fi; \
				fi; \
				;; \
			esac; \
	}; \
	check_variant_requirements; \
	JUPYTER_PORT_SELECTED="$$(pick_random_free_port 200)"; \
	if [[ -z "$$JUPYTER_PORT_SELECTED" ]]; then \
		log_warn "Could not find an available random Jupyter port after multiple attempts."; \
		exit 1; \
	fi; \
	JUPYTER_URL_RUNTIME="http://127.0.0.1:$$JUPYTER_PORT_SELECTED"; \
	MCP_PORT_SELECTED="$$(pick_random_free_port 200)"; \
	if [[ -z "$$MCP_PORT_SELECTED" ]]; then \
		log_warn "Could not find an available random MCP port after multiple attempts."; \
		exit 1; \
	fi; \
	MCP_URL_RUNTIME="http://127.0.0.1:$$MCP_PORT_SELECTED/mcp"; \
	MCP_HEALTH_URL_RUNTIME="http://127.0.0.1:$$MCP_PORT_SELECTED/api/healthz"; \
	log_ok "Base runtime: Jupyter server (always on)"; \
	log_ok "Additional sandbox: $$VARIANT_LABEL"; \
	log_info "$$VARIANT_DESC"; \
	log_info "Selected random Jupyter port: $$JUPYTER_PORT_SELECTED"; \
	log_info "Selected random MCP port: $$MCP_PORT_SELECTED"; \
	if [[ "$$VARIANT" != "none" ]]; then \
		log_info "MCP --sandbox-variant will be set to: $$ENGINE"; \
	fi; \
	log_step "Starting JupyterLab at $$JUPYTER_URL_RUNTIME/lab ..."; \
	jupyter lab \
		--port "$$JUPYTER_PORT_SELECTED" \
		--ip 0.0.0.0 \
		--ServerApp.port_retries 0 \
		--IdentityProvider.token $(JUPYTER_TOKEN) \
		--ServerApp.root_dir $(ROOT_DIR) \
		> .jupyter.log 2>&1 & \
	JUPYTER_PID=$$!; \
	log_step "Waiting for JupyterLab health endpoint..."; \
	wait_for_health "JupyterLab" "$$JUPYTER_URL_RUNTIME/api?token=$(JUPYTER_TOKEN)" "$$JUPYTER_PID" ".jupyter.log" 90; \
	log_step "Starting Jupyter MCP Server at $$MCP_URL_RUNTIME without MCP auth..."; \
	jupyter-mcp-server start \
		--transport streamable-http \
		--sandbox-variant "$$ENGINE" \
		--jupyter-url "$$JUPYTER_URL_RUNTIME" \
		--jupyter-token $(JUPYTER_TOKEN) \
		--document-id $(DOCUMENT_ID) \
		--start-new-runtime true \
		--insecure-mcp-noauth \
		--port "$$MCP_PORT_SELECTED" \
		> .mcp.log 2>&1 & \
	MCP_PID=$$!; \
	log_step "Waiting for Jupyter MCP Server health endpoint..."; \
	wait_for_health "Jupyter MCP Server" "$$MCP_HEALTH_URL_RUNTIME" "$$MCP_PID" ".mcp.log" 90; \
	echo ""; \
	log_warn "MCP endpoint auth is disabled (local dev only)."; \
	log_ok "JupyterLab: $$JUPYTER_URL_RUNTIME/lab?token=$(JUPYTER_TOKEN)"; \
	log_ok "MCP endpoint: $$MCP_URL_RUNTIME"; \
	log_ok "Additional sandbox: $$VARIANT_LABEL"; \
	log_step "Running pydantic-ai CLI with model: $(MODEL)"; \
	echo ""; \
	$(BEDROCK_ENV) \
	PYDANTIC_AI_MODEL="$(MODEL)" \
	JUPYTER_MCP_URL="$$MCP_URL_RUNTIME" \
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
