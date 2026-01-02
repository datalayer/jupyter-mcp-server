# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

# Copyright (c) Datalayer, Inc. https://datalayer.io
# Distributed under the terms of the MIT License.

SHELL=/bin/bash

.DEFAULT_GOAL := deploy

CONDA_ACTIVATE=source $$(conda info --base)/etc/profile.d/conda.sh ; conda activate
CONDA_DEACTIVATE=source $$(conda info --base)/etc/profile.d/conda.sh ; conda deactivate
CONDA_REMOVE=source $$(conda info --base)/etc/profile.d/conda.sh ; conda remove -y --all -n

ENV_NAME=datalayer

.SILENT: init install

.PHONY: build deploy

help: ## display this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

default: help ## default target is help

env-rm:
	-conda remove -y --all -n ${ENV_NAME}

env:
	-conda env create -f environment.yml
	@echo 
	@echo --------------------------------------------------
	@echo 🔧  Datalayer environment is created.
	@echo --------------------------------------------------
	@echo

clean: ## clear
	($(CONDA_ACTIVATE) ${ENV_NAME}; \
	  npm clear )

install: ## install
	($(CONDA_ACTIVATE) ${ENV_NAME}; \
	  npm install )

start: ## start
	($(CONDA_ACTIVATE) ${ENV_NAME}; \
	  npm start )

build: ## build
	($(CONDA_ACTIVATE) ${ENV_NAME}; \
	  npm run build )

deploy: build ## deploy
	($(CONDA_ACTIVATE) ${ENV_NAME}; \
	  aws s3 rm \
			s3://datalayer-jupyter-mcp-server/ \
			--recursive \
			--profile datalayer && \
	  aws s3 cp \
			./build \
			s3://datalayer-jupyter-mcp-server/ \
			--recursive \
			--profile datalayer && \
	  aws cloudfront create-invalidation \
			--distribution-id EP7AV0D2EWHSX \
			--paths "/*" \
			--profile datalayer && \
	echo open 🔧  https://jupyter-mcp-server.datalayer.tech )
