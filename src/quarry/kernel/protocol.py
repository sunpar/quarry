"""Newline-delimited JSON-RPC between the server and a kernel subprocess."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from typing import Final

from pydantic import BaseModel, Field
from pydantic_core import PydanticSerializationError

from quarry.query.spec import Json

_RECV_BYTES: Final = 65536


class Request(BaseModel):
    id: int
    method: str
    params: dict[str, Json] = Field(default_factory=dict)


class RpcError(BaseModel):
    type: str
    message: str


class Response(BaseModel):
    id: int
    result: Json | None = None
    error: RpcError | None = None


def encode(msg: BaseModel) -> bytes:
    """`msg` as one UTF-8 JSON line; a lone surrogate, which UTF-8 cannot carry, becomes "?"."""
    try:
        return msg.model_dump_json(by_alias=True).encode("utf-8") + b"\n"
    except PydanticSerializationError:
        # Text decoded with surrogateescape (odd file names, raw bytes) reaches printed output.
        text = json.dumps(msg.model_dump(mode="json", by_alias=True), ensure_ascii=False)
        return text.encode("utf-8", "replace") + b"\n"


def decode_request(line: bytes) -> Request:
    return Request.model_validate_json(line)


def decode_response(line: bytes) -> Response:
    return Response.model_validate_json(line)


def read_lines(sock: socket.socket) -> Iterator[bytes]:
    """Each newline-terminated line `sock` receives, until the peer closes or the socket fails.

    Chunks of an unfinished line are joined once, so a multi-megabyte line costs linear time.
    """
    partial: list[bytes] = []
    while chunk := _receive(sock):
        first, *rest = chunk.split(b"\n")
        if not rest:
            partial.append(first)
            continue
        *complete, tail = rest
        yield b"".join([*partial, first])
        yield from complete
        partial = [tail]


def _receive(sock: socket.socket) -> bytes:
    try:
        return sock.recv(_RECV_BYTES)
    except OSError:  # reset, or closed under the reader: the same as the peer closing
        return b""
