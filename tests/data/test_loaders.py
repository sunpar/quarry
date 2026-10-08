from pathlib import Path

import pytest

from quarry.data.loaders import describe_loaders, load_loaders


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "loaders.toml"
    path.write_text(body)
    return path


def test_missing_file_is_empty_registry(tmp_path: Path) -> None:
    reg = load_loaders(tmp_path / "loaders.toml")
    assert reg.specs == [] and reg.functions == {} and reg.failures == []


def test_loads_and_binds(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[[loader]]\nname = "daily_returns"\ndescription = "Daily returns"\n'
        'import = "tests.data.fake_firmlib:load_daily"\n'
        'signature = "load_daily(tickers: list[str]) -> pl.DataFrame"\n',
    )
    reg = load_loaders(path)
    assert [s.name for s in reg.specs] == ["daily_returns"]
    assert reg.failures == []
    out = reg.bound().daily_returns(["AAPL"])
    assert out["ticker"].to_list() == ["AAPL"]


def test_bad_import_is_a_failure_not_an_exception(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[[loader]]\nname = "broken"\ndescription = "x"\nimport = "no.such.module:fn"\n'
        'signature = "fn()"\n',
    )
    reg = load_loaders(path)
    assert reg.functions == {}
    assert reg.failures[0].name == "broken"
    assert "no.such.module" in reg.failures[0].error


def test_module_that_raises_on_import_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Firm libraries often connect to something at import time; that must not stop the kernel.
    (tmp_path / "quarry_test_explodes_on_import.py").write_text(
        "raise RuntimeError('license server unreachable')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    path = write(
        tmp_path,
        '[[loader]]\nname = "explodes"\ndescription = "x"\n'
        'import = "quarry_test_explodes_on_import:fn"\nsignature = "fn()"\n',
    )
    reg = load_loaders(path)
    assert reg.functions == {}
    assert reg.failures[0].name == "explodes"
    assert "license server unreachable" in reg.failures[0].error


def test_describe_loaders_renders_one_line_each(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[[loader]]\nname = "daily_returns"\ndescription = "Daily returns"\n'
        'import = "tests.data.fake_firmlib:load_daily"\nsignature = "load_daily(tickers)"\n',
    )
    text = describe_loaders(load_loaders(path))
    assert text == "loaders.daily_returns: load_daily(tickers) -- Daily returns"
