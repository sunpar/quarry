"""Keep Python test processes on loopback and Unix sockets."""

import socket
from typing import Any

_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def require_local(connection: socket.socket, address: Any) -> None:
    """Refuse external TCP connections before opening the transport."""
    if connection.family != socket.AF_UNIX and address[0] not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"External network disabled in local tests: {address[0]}")


def connect(self: socket.socket, address: Any) -> None:
    """Connect to a local service."""
    require_local(self, address)
    _connect(self, address)


def connect_ex(self: socket.socket, address: Any) -> int:
    """Connect to a local service and return its error code."""
    require_local(self, address)
    return _connect_ex(self, address)


for name, method in {"connect": connect, "connect_ex": connect_ex}.items():
    setattr(socket.socket, name, method)
