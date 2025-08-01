# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

from pydantic import BaseModel


class DocumentRuntime(BaseModel):
    provider: str
    document_url: str
    document_id: str
    document_token: str
    runtime_url: str
    runtime_id: str
    runtime_token: str
