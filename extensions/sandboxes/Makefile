# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

SHELL=/bin/bash

publish-pypi: # publish the pypi package
	git clean -fdx && \
		python -m build
	@exec echo
	@exec echo twine upload ./dist/*-py3-none-any.whl
	@exec echo
	@exec echo https://pypi.org/project/jupyter-mcp-sandboxes/#history
