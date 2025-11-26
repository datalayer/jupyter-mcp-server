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
	  -e START_NEW_RUNTIME=true \
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
	  --start-new-runtime true \
	  --port 4040

start-empty: ## start the jupyter mcp server with streamable-http transport and no document nor runtime
	@exec echo
	@exec echo curl http://localhost:4040/api/healthz
	@exec echo
	@exec echo 👉 Define in your favorite mcp client the server http://localhost:4040/mcp
	@exec echo
	jupyter-mcp-server start \
	  --transport streamable-http \
	  --jupyter-url http://localhost:8888 \
	  --jupyter-token MY_TOKEN \
	  --start-new-runtime false \
	  --port 4040

start-jupyter-server-extension: ## start jupyter server with MCP extension
	@exec echo
	@exec echo 🚀 Starting Jupyter Server with MCP Extension
	@exec echo 📍 Using local serverapp access - document_url=local, runtime_url=local
	@exec echo
	@exec echo 🔗 JupyterLab will be available at http://localhost:4040/lab
	@exec echo 🔗 MCP endpoints will be available at http://localhost:4040/mcp
	@exec echo
	@exec echo "Test with: curl http://localhost:4040/mcp/healthz"
	@exec echo
	jupyter lab \
	  --JupyterMCPServerExtensionApp.document_url local \
	  --JupyterMCPServerExtensionApp.runtime_url local \
	  --JupyterMCPServerExtensionApp.document_id notebook.ipynb \
	  --JupyterMCPServerExtensionApp.start_new_runtime True \
	  --ServerApp.disable_check_xsrf True \
	  --IdentityProvider.token MY_TOKEN \
	  --ServerApp.root_dir ./dev/content \
	  --port 4040

jupyterlab: ## start jupyterlab for the mcp server
	pip uninstall -y pycrdt datalayer_pycrdt
	pip install datalayer_pycrdt
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
