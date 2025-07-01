# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

SHELL=/bin/bash

.DEFAULT_GOAL := default

.PHONY: clean build

VERSION = 0.6.0

default: all ## default target is all

help: ## display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

all: clean build ## clean and build

install:
	pip install .

dev:
	pip install ".[test,lint,typing]"

build:
	pip install build
	python -m build .

clean: ## clean
	git clean -fdx

build-docker: ## build the docker image
	docker buildx build --platform linux/amd64,linux/arm64 --push -t datalayer/jupyter-mcp-server:${VERSION} .
	docker buildx build --platform linux/amd64,linux/arm64 --push -t datalayer/jupyter-mcp-server:latest .
#	docker image tag datalayer/jupyter-mcp-server:${VERSION} datalayer/jupyter-mcp-server:latest

start-docker: ## start the jupyter mcp server in docker
	docker run -i --rm \
	  -e ROOM_URL=http://localhost:8888 \
	  -e ROOM_ID=notebook.ipynb \
	  -e ROOM_TOKEN=MY_TOKEN \
	  -e RUNTIME_URL=http://localhost:8888 \
	  -e START_NEW_RUNTIME=true \
	  -e RUNTIME_TOKEN=MY_TOKEN \
	  --network=host \
	  datalayer/jupyter-mcp-server:latest

pull-docker: ## pull the latest docker image
	docker image pull datalayer/jupyter-mcp-server:latest

push-docker: ## push the docker image to the registry
	docker push datalayer/jupyter-mcp-server:${VERSION}
	docker push datalayer/jupyter-mcp-server:latest

claude-linux: ## run the claude desktop linux app using nix
	NIXPKGS_ALLOW_UNFREE=1 nix run github:k3d3/claude-desktop-linux-flake?rev=6d9eb2a653be8a6c06bc29a419839570e0ffc858 \
		--impure \
		--extra-experimental-features flakes \
		--extra-experimental-features nix-command

# python -m jupyter_mcp_server
start: ## start the jupyter mcp server with streamable-http transport
	@exec echo curl http://localhost:4040/api/healthz
	@exec echo
	jupyter-mcp-server start \
	  --transport streamable-http \
	  --room-url http://localhost:8888 \
	  --room-id notebook.ipynb \
	  --room-token MY_TOKEN \
	  --runtime-url http://localhost:8888 \
	  --start-new-runtime true \
	  --runtime-token MY_TOKEN \
	  --port 4040

jupyterlab: ## start jupyterlab for the mcp server
	pip uninstall -y pycrdt datalayer_pycrdt
	pip install datalayer_pycrdt
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
