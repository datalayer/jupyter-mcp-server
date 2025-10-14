# Copyright (c) 2023-2024 Datalayer, Inc.
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

RUN pip install --no-cache-dir -e . && \
    pip uninstall -y pycrdt datalayer_pycrdt && \
    pip install --no-cache-dir datalayer_pycrdt==0.12.17

EXPOSE 4040

ENTRYPOINT ["python", "-m", "jupyter_mcp_server"]
