import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quarry.agent.context import enabled_libraries
from quarry.config import LibrariesConfig, QuarryConfig
from quarry.libraries import licensed_libraries
from tests.server.test_app import make_client


def config_with(tmp_path: Path, **libraries: str | Path) -> QuarryConfig:
    return QuarryConfig(root=tmp_path, libraries=LibrariesConfig(**libraries))


def fake_package(root: Path, name: str, entry: str) -> Path:
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / entry).write_text("// stub")
    return pkg


def test_license_without_path_warns_once_and_stays_disabled(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = config_with(tmp_path, scichart_license="sc-key-7f3q")
    with (
        caplog.at_level(logging.WARNING, logger="quarry.server.app"),
        make_client(tmp_path, [], config=config) as client,
    ):
        listed = {s["id"]: s for s in client.get("/libraries").json()}
        client.get("/libraries")
        assert client.get("/libs/scichart/index.min.mjs").status_code == 404
    assert listed["scichart"] == {
        "id": "scichart",
        "enabled": False,
        "reason": "scichart_path is not set",
        "license": None,
        "entry": None,
    }
    messages = [r.getMessage() for r in caplog.records if r.name == "quarry.server.app"]
    assert len(messages) == 1 and "scichart" in messages[0]
    assert "sc-key-7f3q" not in caplog.text
    assert "scichart" not in enabled_libraries(config)


def test_missing_path_is_reported_and_disabled(tmp_path: Path) -> None:
    config = config_with(tmp_path, highcharts_license="k", highcharts_path=tmp_path / "nope")
    status = next(s for s in licensed_libraries(config) if s.id == "highcharts")
    assert status.enabled is False and "does not exist" in (status.reason or "")


def test_enabled_library_is_mounted_with_cors_and_listed(tmp_path: Path) -> None:
    hc = fake_package(tmp_path, "highcharts", "highstock.js")
    sc = fake_package(tmp_path, "scichart", "index.min.mjs")
    config = config_with(
        tmp_path,
        highcharts_license="k1",
        highcharts_path=hc,
        scichart_license="k2",
        scichart_path=sc,
    )
    with make_client(tmp_path, [], config=config) as client:
        listed = {s["id"]: s for s in client.get("/libraries").json()}
        assert listed["highcharts"] == {
            "id": "highcharts",
            "enabled": True,
            "reason": None,
            "license": "k1",
            "entry": "/libs/highcharts/highstock.js",
        }
        assert listed["scichart"]["entry"] == "/libs/scichart/index.min.mjs"
        served = client.get("/libs/highcharts/highstock.js", headers={"Origin": "null"})
        assert served.status_code == 200 and served.headers["access-control-allow-origin"] == "*"
    bare = TestClient(client.app)  # no Authorization header at all
    assert bare.get("/libraries").status_code == 401
    assert enabled_libraries(config) == [
        *enabled_libraries(QuarryConfig(root=tmp_path)),
        "highcharts",
        "scichart",
    ]


def test_unlicensed_library_is_not_mounted(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        assert client.get("/libs/highcharts/highstock.js").status_code == 404
        listed = [(s["id"], s["enabled"]) for s in client.get("/libraries").json()]
    assert listed == [("highcharts", False), ("scichart", False)]
