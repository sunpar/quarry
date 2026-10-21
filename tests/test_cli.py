import json
import re
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from quarry.cli import banner, free_port, main, new_token
from tests.fixtures import umask
from tests.projects.test_export import project_with_saved_items


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


@pytest.mark.parametrize("argv", [[], ["projects"]], ids=["no_command", "no_project_command"])
def test_main_without_command_prints_usage(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert main(argv) == 2
    assert capsys.readouterr().err.startswith("usage: quarry")


def test_serve_binds_loopback_and_banner_token_is_the_app_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    app = object()
    app_calls: list[dict[str, Any]] = []
    run_calls: list[uvicorn.Config] = []

    def fake_create_app(**kwargs: Any) -> object:
        app_calls.append(kwargs)
        return app

    def fake_run(server: uvicorn.Server) -> None:
        run_calls.append(server.config)

    monkeypatch.setattr("quarry.cli.create_app", fake_create_app)
    monkeypatch.setattr("quarry.cli.QuarryServer.run", fake_run)
    root = tmp_path / "root"

    code = main(["serve", "--port", "4321", "--root", str(root), "--host-hint", "devbox"])

    assert code == 0
    assert root.is_dir()
    assert len(run_calls) == 1
    config = run_calls[0]
    assert config.app is app
    assert config.host == "127.0.0.1"
    assert config.port == 4321
    assert config.log_level == "warning"
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
    monkeypatch.setattr("quarry.cli.QuarryServer.run", lambda _: None)
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


@pytest.mark.parametrize("format_name, extension", [("notebook", "ipynb"), ("html", "html")])
def test_exports_replace_existing_outputs_privately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format_name: str, extension: str
) -> None:
    project_with_saved_items(tmp_path)
    monkeypatch.chdir(tmp_path)
    target = tmp_path / f"momentum.{extension}"
    target.write_text("old output")
    target.chmod(0o644)
    with umask(0o022):
        assert (
            main(
                ["projects", "export", "momentum", "--root", str(tmp_path), "--format", format_name]
            )
            == 0
        )
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text() != "old output"
    if format_name == "html":
        assert "Live results unavailable" in target.read_text()


def test_html_export_failure_leaves_output_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_with_saved_items(tmp_path)
    (tmp_path / "projects/momentum/views/table/state.json").write_text("corrupt")
    target = tmp_path / "report.html"
    target.write_text("previous report")
    assert (
        main(
            [
                "projects",
                "export",
                "momentum",
                "--root",
                str(tmp_path),
                "--format",
                "html",
                "--out",
                str(target),
            ]
        )
        == 1
    )
    assert target.read_text() == "previous report"
    assert "saved artifact" in capsys.readouterr().err


@pytest.mark.parametrize("format_name, extension", [("notebook", "ipynb"), ("html", "html")])
@pytest.mark.parametrize("symlink", [False, True])
def test_exports_do_not_reuse_preexisting_temporary_files(
    tmp_path: Path, format_name: str, extension: str, symlink: bool
) -> None:
    project_with_saved_items(tmp_path)
    target = tmp_path / f"report.{extension}"
    previous_temp = tmp_path / f".report.{extension}.tmp"
    victim = tmp_path / "unrelated.txt"
    victim.write_text("leave this alone")
    if symlink:
        previous_temp.symlink_to(victim)
    else:
        previous_temp.write_text("old temporary file")
        previous_temp.chmod(0o644)
    assert (
        main(
            [
                "projects",
                "export",
                "momentum",
                "--root",
                str(tmp_path),
                "--format",
                format_name,
                "--out",
                str(target),
            ]
        )
        == 0
    )
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert victim.read_text() == "leave this alone"
    assert previous_temp.read_text() == ("leave this alone" if symlink else "old temporary file")


@pytest.mark.parametrize("format_name", ["notebook", "html"])
def test_missing_recipe_is_an_export_failure_for_an_existing_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], format_name: str
) -> None:
    project_with_saved_items(tmp_path)
    (tmp_path / "projects/momentum/datasets/prices/recipe.py").unlink()
    target = tmp_path / "report"
    target.write_text("previous export")
    assert (
        main(
            [
                "projects",
                "export",
                "momentum",
                "--root",
                str(tmp_path),
                "--format",
                format_name,
                "--out",
                str(target),
            ]
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "export failed" in error and "no such project" not in error
    assert target.read_text() == "previous export"


def test_an_export_into_a_missing_directory_is_an_export_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_with_saved_items(tmp_path)
    out = str(tmp_path / "missing" / "out.ipynb")
    assert main(["projects", "export", "momentum", "--root", str(tmp_path), "--out", out]) == 1
    err = capsys.readouterr().err
    # The write is what failed: the message names the target, not write_atomic's temp file.
    assert err.startswith("export failed: ") and out in err and ".tmp" not in err
    assert not (tmp_path / "missing").exists()


def test_an_unreadable_config_is_an_export_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_with_saved_items(tmp_path)
    (tmp_path / "config.toml").mkdir()
    out = str(tmp_path / "out.ipynb")
    assert main(["projects", "export", "momentum", "--root", str(tmp_path), "--out", out]) == 1
    assert "export failed: config file unreadable" in capsys.readouterr().err
