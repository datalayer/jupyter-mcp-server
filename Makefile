# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

SHELL=/bin/bash

.DEFAULT_GOAL := default

.PHONY: clean build

VERSION = 0.2

default: all ## default target is all

help: ## display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

all: clean build ## clean and build

install:
	pip install .

dev:
	pip install ".[test,lint,typing]"

test: ## run the unit tests
	git checkout ./dev/content && \
	TEST_MCP_SERVER=true \
	TEST_JUPYTER_SERVER=true \
	pytest

test-extensions: ## run the unit tests of the extensions under extensions/
	@# Their own tests, run on their own. A bare `pytest` collects them too,
	@# but twice — once per server mode — and reports them under whichever
	@# mode happened to run, which is neither true nor useful when one fails.
	@# These need no Jupyter server and take seconds.
	pytest extensions/sandboxes/tests

test-examples: ## run the tests of the examples under examples/
	@# Each example has a test module beside it, driven by pydantic-ai's test
	@# models, so no LLM credentials are needed. They need the example's own
	@# dependencies: `pip install -r examples/cli/requirements.txt`.
	pytest examples

test-mcp-server: ## run the unit tests for mcp server
	git checkout ./dev/content && \
	TEST_MCP_SERVER=true \
	TEST_JUPYTER_SERVER=false \
	pytest

test-jupyter-server: ## run the unit tests for jupyter server
	git checkout ./dev/content && \
	TEST_MCP_SERVER=false \
	TEST_JUPYTER_SERVER=true \
	pytest

test-integration: ## run the integration tests
	hatch test

.PHONY: bump bump-patch bump-minor bump-major

bump: ## bump the version, asking which part
	python dev/bump_version.py

bump-patch: ## bump the patch version (2.1.3 -> 2.1.4)
	python dev/bump_version.py patch

bump-minor: ## bump the minor version (2.1.3 -> 2.2.0)
	python dev/bump_version.py minor

bump-major: ## bump the major version (2.1.3 -> 3.0.0)
	python dev/bump_version.py major

build:
	pip install build
	python -m build .

clean: ## clean
	git clean -fdx

build-docker: ## build the docker image
	docker buildx build --platform linux/amd64,linux/arm64 --push -t datalayer/jupyter-mcp-server:${VERSION} .
	docker buildx build --platform linux/amd64,linux/arm64 --push -t datalayer/jupyter-mcp-server:latest .
#	docker image tag datalayer/jupyter-mcp-server:${VERSION} datalayer/jupyter-mcp-server:latest
	@exec echo open https://hub.docker.com/r/datalayer/jupyter-mcp-server/tags

start-docker: ## start the jupyter mcp server in docker
	docker run -i --rm \
	  -e JUPYTER_URL=http://localhost:8888 \
	  -e JUPYTER_TOKEN=MY_TOKEN \
	  -e START_NEW_CODE_SANDBOX=true \
	  --network=host \
	  datalayer/jupyter-mcp-server:latest

pull-docker: ## pull the latest docker image
	docker image pull datalayer/jupyter-mcp-server:latest

push-docker: ## push the docker image to the registry
	docker push datalayer/jupyter-mcp-server:${VERSION}
	docker push datalayer/jupyter-mcp-server:latest
	@exec echo open https://hub.docker.com/r/datalayer/jupyter-mcp-server/tags

claude-linux: ## run the claude desktop linux app using nix
	NIXPKGS_ALLOW_UNFREE=1 nix run github:k3d3/claude-desktop-linux-flake?rev=6d9eb2a653be8a6c06bc29a419839570e0ffc858 \
		--impure \
		--extra-experimental-features flakes \
		--extra-experimental-features nix-command

start: ## start the jupyter mcp server with streamable-http transport
	@exec echo
	@exec echo curl http://localhost:4040/api/healthz
	@exec echo
	@exec echo 👉 Define in your favorite mcp client the server http://localhost:4040/mcp
	@exec echo
	jupyter-mcp-server start \
	  --transport streamable-http \
	  --jupyter-url http://localhost:8888 \
	  --jupyter-token MY_TOKEN \
	  --start-new-code-sandbox true \
	  --port 4040

start-empty: ## start the jupyter mcp server with streamable-http transport and no document nor code sandbox
	@exec echo
	@exec echo curl http://localhost:4040/api/healthz
	@exec echo
	@exec echo 👉 Define in your favorite mcp client the server http://localhost:4040/mcp
	@exec echo
	jupyter-mcp-server start \
	  --transport streamable-http \
	  --jupyter-url http://localhost:8888 \
	  --jupyter-token MY_TOKEN \
	  --start-new-code-sandbox false \
	  --port 4040

start-jupyter-server-extension: ## start jupyter server with MCP extension
	@exec echo
	@exec echo 🚀 Starting Jupyter Server with MCP Extension
	@exec echo 📍 Using local serverapp access - document_url=local, code_sandbox_url=local
	@exec echo
	@exec echo 🔗 JupyterLab will be available at http://localhost:4040/lab
	@exec echo 🔗 MCP endpoints will be available at http://localhost:4040/mcp
	@exec echo
	@exec echo "Test with: curl http://localhost:4040/mcp/healthz"
	@exec echo
	jupyter lab \
	  --JupyterMCPServerExtensionApp.document_url local \
	  --JupyterMCPServerExtensionApp.code_sandbox_url local \
	  --JupyterMCPServerExtensionApp.document_id notebook.ipynb \
	  --JupyterMCPServerExtensionApp.start_new_code_sandbox True \
	  --ServerApp.disable_check_xsrf True \
	  --IdentityProvider.token MY_TOKEN \
	  --ServerApp.root_dir ./dev/content \
	  --port 4040

jupyterlab: ## start jupyterlab for the mcp server
	@exec echo
	@exec echo curl http://localhost:8888/lab?token=MY_TOKEN
	@exec echo
	jupyter lab \
		--port 8888 \
		--ip 0.0.0.0 \
		--ServerApp.root_dir ./dev/content \
		--IdentityProvider.token MY_TOKEN

publish-pypi: # publish the pypi package
	git clean -fdx && \
		python -m build
	@exec echo
	@exec echo twine upload ./dist/*-py3-none-any.whl
	@exec echo
	@exec echo https://pypi.org/project/jupyter-mcp-server/#history

.PHONY: test-conformance
test-conformance: ## Run the MCP specification's own conformance suite
	@exec echo "Installing @modelcontextprotocol/conformance (npm, not saved)"
	npm install --no-save @modelcontextprotocol/conformance
	pytest tests/test_conformance.py -v

.PHONY: sync-sourcey

SOURCEY_SNAPSHOT_TIMEOUT ?= 180

# The extension entry-point names this repo publishes, read out of its own
# pyproject files: the root package and everything under extensions/.
SOURCEY_REPO_EXTENSIONS = python -c 'import glob,tomllib;fs=["pyproject.toml"]+sorted(glob.glob("extensions/*/pyproject.toml"));print(",".join(sorted({n for f in fs for n in ((tomllib.load(open(f,"rb")).get("project") or {}).get("entry-points") or {}).get("jupyter_mcp_server.extensions",{}) or {}})))'

sync-sourcey: ## regenerate the generated MCP reference under docs/sourcey
	@# The four steps of the Docs workflow's "Regenerate the MCP reference",
	@# plus the `npm install` it runs first: docs/ has its own package.json and
	@# is not one of the monorepo workspaces, so a root `npm i` never installs
	@# mcp-parser for it and step 1 dies with ERR_MODULE_NOT_FOUND.
	@command -v jupyter-mcp-server >/dev/null 2>&1 || { \
	  echo "jupyter-mcp-server is not on PATH."; \
	  echo "Run 'make dev' and 'pip install ./extensions/sandboxes' first."; \
	  exit 1; }
	cd docs && npm install --no-audit --no-fund
	@# Step 1 spawns the server over stdio. It used to sit there for two
	@# minutes after writing mcp.json -- mcp-parser leaves a per-request timer
	@# armed -- which snapshot.mjs now ends explicitly; see the comment at the
	@# foot of that file. `timeout` stays as a backstop for a server that never
	@# answers at all, and stdin is closed so the child cannot read the
	@# terminal. Whatever the exit status, the snapshot has to be usable, so
	@# the artifact is checked before the three steps that consume it.
	@# The snapshot is whatever the installed server advertises, so an
	@# environment carrying an extension beyond the ones this repo ships
	@# answers differently and the reference stops matching CI, which installs
	@# only . and ./extensions/sandboxes. JUPYTER_MCP_EXTENSIONS pins discovery
	@# to the entry-point names declared by this repo's own pyproject files --
	@# read from them rather than written down here, so adding an extension
	@# needs no edit.
	exts=$$($(SOURCEY_REPO_EXTENSIONS)) ; \
	echo "snapshotting with extensions: $$exts" ; \
	cd docs/sourcey && \
	  if command -v timeout >/dev/null 2>&1 ; then \
	    JUPYTER_MCP_EXTENSIONS="$$exts" timeout --foreground -k 5 $(SOURCEY_SNAPSHOT_TIMEOUT) \
	      node snapshot.mjs jupyter-mcp-server mcp.json </dev/null ; \
	  else \
	    JUPYTER_MCP_EXTENSIONS="$$exts" \
	      node snapshot.mjs jupyter-mcp-server mcp.json </dev/null ; \
	  fi ; \
	  status=$$? ; \
	  if [ $$status -eq 124 ] ; then \
	    echo "snapshot.mjs did not finish within $(SOURCEY_SNAPSHOT_TIMEOUT)s - is a Jupyter server reachable?" ; \
	    exit 1 ; \
	  elif [ $$status -ne 0 ] ; then \
	    exit $$status ; \
	  fi ; \
	  python -m json.tool mcp.json >/dev/null 2>&1 || { \
	    echo "mcp.json is not valid JSON - the snapshot did not complete" ; exit 1 ; } ; \
	  python -c 'import json,sys; d=json.load(open("mcp.json")); t=len(d.get("tools") or []); p=len(d.get("prompts") or []); print("snapshot ok: %d tools, %d prompt(s)" % (t,p)) if t else sys.exit("mcp.json carries no tools - the snapshot did not complete")'
	cd docs/sourcey && \
	  python gen_sourcemap.py ../.. sourcemap.json && \
	  python dump_config.py config-fields.json && \
	  node build_pages.mjs
	@exec echo
	@exec echo "docs/sourcey regenerated - commit whatever changed, that is what CI checks."
