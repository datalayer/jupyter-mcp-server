# Copyright (c) 2023-2024 Datalayer, Inc.
#
# BSD 3-Clause License

from pydantic import BaseModel


class RoomRuntime(BaseModel):
    provider: str
    room_url: str
    room_id: str
    room_token: str
    runtime_url: str
    runtime_id: str
    runtime_token: str
