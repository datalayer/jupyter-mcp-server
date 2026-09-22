# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml LICENSE README.md ./
COPY jupyter_mcp_server/ jupyter_mcp_server/
COPY jupyter-config/ jupyter-config/

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m pip install --upgrade pip wheel setuptools && pip --version

RUN pip install --no-cache-dir -e .

EXPOSE 4040

# The --host option defaults to loopback so that a pip install does not put the
# streamable-HTTP listener on every interface. That default is wrong for this image:
# Docker forwards a published port to the container's eth0 address, not to its
# loopback, so a 127.0.0.1 bind would make `-p 4040:4040` accept nothing. Binding
# every interface *inside the container's own network namespace* is what the
# published-port recipe needs, and reaching it still requires the operator to
# publish the port. An explicit --host on the command line overrides this.
ENV HOST=0.0.0.0

ENTRYPOINT ["python", "-m", "jupyter_mcp_server"]
