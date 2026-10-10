import json
import re
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from quarry.cli import banner, free_port, main, new_token
from tests.fixtures import umask


def test_banner_contains_tunnel_and_url() -> None:
    text = banner(port=4321, token="abc", host_hint="devbox")
    assert "ssh -L 4321:127.0.0.1:4321 devbox" in text
    assert "http://127.0.0.1:4321/#token=abc" in text


def test_free_port_is_usable() -> None:
    port = free_port()
    assert 1024 < port < 65536


def test_token_is_long_and_url_safe() -> None:
    token = new_token()
    assert len(token) >= 40 and all(c.isalnum() or c in "-_" for c in token)


def test_main_without_command_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "serve" in capsys.readouterr().err


def test_serve_binds_loopback_and_banner_token_is_the_app_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    app = object()
    app_calls: list[dict[str, Any]] = []
    run_calls: list[tuple[object, dict[str, Any]]] = []

    def fake_create_app(**kwargs: Any) -> object:
        app_calls.append(kwargs)
        return app

    def fake_run(served: object, **kwargs: Any) -> None:
        run_calls.append((served, kwargs))

    monkeypatch.setattr("quarry.cli.create_app", fake_create_app)
    monkeypatch.setattr("quarry.cli.uvicorn.run", fake_run)
    root = tmp_path / "root"

    code = main(["serve", "--port", "4321", "--root", str(root), "--host-hint", "devbox"])

    assert code == 0
    assert root.is_dir()
    assert len(run_calls) == 1
    served, run_kwargs = run_calls[0]
    assert served is app
    assert run_kwargs["host"] == "127.0.0.1"
    assert run_kwargs["port"] == 4321
    out = capsys.readouterr().out
    match = re.search(r"^Token \(keep private\): (\S+)$", out, re.MULTILINE)
    assert match is not None
    assert len(app_calls) == 1
    assert app_calls[0]["token"] == match.group(1)
    assert app_calls[0]["config"].root == root
    assert "devbox" in out and "4321" in out


@pytest.fixture
def serve_stubs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`quarry serve` with the app and server stubbed, under a umask that lets others in."""
    monkeypatch.setattr("quarry.cli.create_app", lambda **_: object())
    monkeypatch.setattr("quarry.cli.uvicorn.run", lambda *_, **__: None)
    with umask(0o022):
        yield


@pytest.mark.usefixtures("serve_stubs")
def test_serve_creates_a_missing_root_private(tmp_path: Path) -> None:
    root = tmp_path / "root"
    assert main(["serve", "--port", "4321", "--root", str(root)]) == 0
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


@pytest.mark.usefixtures("serve_stubs")
def test_serve_leaves_an_existing_root_mode_alone(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir(mode=0o755)
    assert main(["serve", "--port", "4321", "--root", str(root)]) == 0
    assert stat.S_IMODE(root.stat().st_mode) == 0o755


def test_projects_list_and_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tests.projects.test_export import project_with_saved_items

    project_with_saved_items(tmp_path)
    assert main(["projects", "list", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "momentum" in out and "Momentum" in out
    target = tmp_path / "out.ipynb"
    assert (
        main(["projects", "export", "momentum", "--root", str(tmp_path), "--out", str(target)]) == 0
    )
    assert json.loads(target.read_text())["nbformat"] == 4
    assert main(["projects", "export", "nope", "--root", str(tmp_path)]) == 1
    assert "no such project" in capsys.readouterr().err
