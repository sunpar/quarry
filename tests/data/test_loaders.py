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


FAKE_LOADER = "tests.data.fake_firmlib:load_daily"


def entry(name: str, target: str = FAKE_LOADER) -> str:
    return (
        f'[[loader]]\nname = "{name}"\ndescription = "d"\nimport = "{target}"\nsignature = "f()"\n'
    )


def test_toml_syntax_error_is_one_failure(tmp_path: Path) -> None:
    reg = load_loaders(write(tmp_path, '[[loader]\nname = "daily_returns"\n'))
    assert reg.specs == [] and reg.functions == {}
    assert [f.name for f in reg.failures] == ["loaders.toml"]
    assert "TOMLDecodeError" in reg.failures[0].error


def test_loader_table_instead_of_array_is_one_failure(tmp_path: Path) -> None:
    body = f'[loader]\nname = "daily_returns"\nimport = "{FAKE_LOADER}"\n'
    reg = load_loaders(write(tmp_path, body))
    assert reg.specs == [] and reg.functions == {}
    assert [f.name for f in reg.failures] == ["loaders.toml"]
    assert "[[loader]]" in reg.failures[0].error


def test_entry_missing_a_field_is_skipped_and_others_bind(tmp_path: Path) -> None:
    no_signature = f'[[loader]]\nname = "no_sig"\ndescription = "d"\nimport = "{FAKE_LOADER}"\n'
    no_name = f'[[loader]]\ndescription = "d"\nimport = "{FAKE_LOADER}"\nsignature = "f()"\n'
    reg = load_loaders(write(tmp_path, no_signature + no_name + entry("daily_returns")))
    assert [f.name for f in reg.failures] == ["no_sig", "loader[1]"]
    assert "signature" in reg.failures[0].error
    assert "name" in reg.failures[1].error
    assert [s.name for s in reg.specs] == ["daily_returns"]
    assert reg.bound().daily_returns(["X"])["ticker"].to_list() == ["X"]


def test_duplicate_name_keeps_the_first_entry(tmp_path: Path) -> None:
    body = entry("daily_returns") + entry("daily_returns", "no.such.module:fn")
    reg = load_loaders(write(tmp_path, body))
    assert [f.name for f in reg.failures] == ["daily_returns"]
    assert "duplicate" in reg.failures[0].error
    assert [s.name for s in reg.specs] == ["daily_returns"]
    assert reg.bound().daily_returns(["X"])["ticker"].to_list() == ["X"]
    assert describe_loaders(reg) == "loaders.daily_returns: f() -- d"


def test_name_that_is_not_an_identifier_is_skipped(tmp_path: Path) -> None:
    body = entry("daily-returns") + entry("class") + entry("daily_returns")
    reg = load_loaders(write(tmp_path, body))
    assert [f.name for f in reg.failures] == ["daily-returns", "class"]
    assert all("identifier" in f.error for f in reg.failures)
    assert list(reg.functions) == ["daily_returns"]
