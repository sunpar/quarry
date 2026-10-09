import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from quarry.data import loaders
from quarry.data.loaders import describe_failures, describe_loaders, load_loaders
from tests.fixtures import chmodded, root_ignores_modes


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


def test_module_that_exits_on_import_is_a_failure_and_the_rest_still_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "quarry_test_exits_on_import.py").write_text(
        "import sys\nsys.exit('no license for this host')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    path = write(
        tmp_path, entry("exits", "quarry_test_exits_on_import:fn") + entry("daily_returns")
    )
    reg = load_loaders(path)
    assert list(reg.functions) == ["daily_returns"]
    assert [f.name for f in reg.failures] == ["exits"]
    assert reg.failures[0].error == (
        "quarry_test_exits_on_import:fn: SystemExit: no license for this host"
    )


def test_import_error_that_cannot_print_itself_is_a_failure_and_the_rest_still_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "quarry_test_unprintable_on_import.py").write_text(
        "class Unprintable(Exception):\n"
        "    def __str__(self):\n"
        "        raise ValueError('cannot print')\n"
        "\n"
        "raise Unprintable\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    path = write(
        tmp_path,
        entry("unprintable", "quarry_test_unprintable_on_import:fn") + entry("daily_returns"),
    )
    reg = load_loaders(path)
    assert list(reg.functions) == ["daily_returns"]
    assert [f.name for f in reg.failures] == ["unprintable"]
    assert reg.failures[0].error == (
        "quarry_test_unprintable_on_import:fn: Unprintable: <unprintable Unprintable>"
    )


def test_module_interrupted_on_import_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "quarry_test_interrupted_on_import.py").write_text("raise KeyboardInterrupt\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    path = write(tmp_path, entry("interrupted", "quarry_test_interrupted_on_import:fn"))
    with pytest.raises(KeyboardInterrupt):
        load_loaders(path)


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
    assert describe_failures(reg).startswith("daily_returns: ")
    assert "duplicate" in describe_failures(reg)


def test_name_that_is_not_an_identifier_is_skipped(tmp_path: Path) -> None:
    body = entry("daily-returns") + entry("class") + entry("daily_returns")
    reg = load_loaders(write(tmp_path, body))
    assert [f.name for f in reg.failures] == ["daily-returns", "class"]
    assert all("identifier" in f.error for f in reg.failures)
    assert list(reg.functions) == ["daily_returns"]


@root_ignores_modes
def test_unreadable_file_is_one_failure(tmp_path: Path) -> None:
    path = write(tmp_path, entry("daily_returns"))
    with chmodded(path, 0o000):
        reg = load_loaders(path)
    assert reg.specs == [] and reg.functions == {}
    assert [f.name for f in reg.failures] == ["loaders.toml"]
    assert "PermissionError" in reg.failures[0].error


@root_ignores_modes
def test_unreadable_directory_is_one_failure(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = write(home, entry("daily_returns"))
    with chmodded(home, 0o000):
        reg = load_loaders(path)
    assert reg.specs == [] and reg.functions == {}
    assert [f.name for f in reg.failures] == ["loaders.toml"]
    assert "PermissionError" in reg.failures[0].error


def test_directory_in_place_of_the_file_is_one_failure(tmp_path: Path) -> None:
    (tmp_path / "loaders.toml").mkdir()
    reg = load_loaders(tmp_path / "loaders.toml")
    assert [f.name for f in reg.failures] == ["loaders.toml"]


def slow_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seconds: float) -> Path:
    (tmp_path / "quarry_test_slow_import.py").write_text(
        f"import time\ntime.sleep({seconds})\n\ndef fn():\n    return 1\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    # setitem remembers the module as absent, so teardown drops it again after the import adds it
    # and a rerun in the same process imports it afresh.
    monkeypatch.setitem(sys.modules, "quarry_test_slow_import", ModuleType("placeholder"))
    monkeypatch.delitem(sys.modules, "quarry_test_slow_import")
    return write(tmp_path, entry("slow", "quarry_test_slow_import:fn"))


def test_slow_import_is_named_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(loaders, "IMPORT_NOTICE_SECONDS", 0.05)
    reg = load_loaders(slow_module(tmp_path, monkeypatch, 0.4))
    assert list(reg.functions) == ["slow"]
    assert capsys.readouterr().err == (
        "quarry: still importing loader slow (quarry_test_slow_import:fn) after 0.05 s\n"
    )


def record_timers(monkeypatch: pytest.MonkeyPatch) -> list[threading.Timer]:
    timers: list[threading.Timer] = []

    class RecordedTimer(threading.Timer):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            timers.append(self)

    monkeypatch.setattr(threading, "Timer", RecordedTimer)
    return timers


def test_import_that_returns_in_time_cancels_its_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A threshold no import reaches, so nothing here depends on how fast the machine is: a timer
    # still waiting after the load returned was not cancelled.
    monkeypatch.setattr(loaders, "IMPORT_NOTICE_SECONDS", 60)
    timers = record_timers(monkeypatch)
    reg = load_loaders(write(tmp_path, entry("daily_returns")))
    assert list(reg.functions) == ["daily_returns"]
    assert len(timers) == 1
    timers[0].join(timeout=5)
    assert not timers[0].is_alive()
    assert capsys.readouterr().err == ""


def test_failed_import_cancels_its_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(loaders, "IMPORT_NOTICE_SECONDS", 60)
    timers = record_timers(monkeypatch)
    reg = load_loaders(write(tmp_path, entry("broken", "no.such.module:fn")))
    assert [f.name for f in reg.failures] == ["broken"]
    assert len(timers) == 1
    timers[0].join(timeout=5)
    assert not timers[0].is_alive()
    assert capsys.readouterr().err == ""
