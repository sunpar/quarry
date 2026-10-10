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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def serve(tmp_path: Path) -> Iterator[Callable[[list[AssistantTurn]], RunningServer]]:
    if not (STATIC / "index.html").exists():
        pytest.skip("web build missing; run `npm run build` in web/")
    servers: list[uvicorn.Server] = []

    def start(turns: list[AssistantTurn]) -> RunningServer:
        config = QuarryConfig(root=tmp_path)
        provider = FakeProvider(turns)
        app = create_app(
            config=config,
            token=TOKEN,
            provider_factory=lambda _cfg: provider,
            static_dir=STATIC,
        )
        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        servers.append(server)
        return RunningServer(base_url=f"http://127.0.0.1:{port}", token=TOKEN, provider=provider)

    yield start
    for server in servers:
        server.should_exit = True
