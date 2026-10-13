from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn
from quarry.config import QuarryConfig
from quarry.server.app import create_app

STATIC = Path(__file__).resolve().parents[2] / "src" / "quarry" / "static"
TOKEN = "e2e-token"


@dataclass(slots=True)
class RunningServer:
    base_url: str
    token: str
    provider: FakeProvider


@pytest.fixture
def serve(tmp_path: Path) -> Iterator[Callable[[list[AssistantTurn]], RunningServer]]:
    if not (STATIC / "index.html").exists():
        pytest.skip("web build missing; run `npm run build` in web/")
    servers: list[tuple[uvicorn.Server, threading.Thread, socket.socket]] = []

    def start(turns: list[AssistantTurn]) -> RunningServer:
        config = QuarryConfig(root=tmp_path)
        provider = FakeProvider(turns)
        app = create_app(
            config=config,
            token=TOKEN,
            provider_factory=lambda _cfg: provider,
            static_dir=STATIC,
        )
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        listener = server.config.bind_socket()
        port = int(listener.getsockname()[1])
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        servers.append((server, thread, listener))
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return RunningServer(base_url=f"http://127.0.0.1:{port}", token=TOKEN, provider=provider)

    yield start
    for server, thread, listener in servers:
        server.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive(), "server did not stop"
