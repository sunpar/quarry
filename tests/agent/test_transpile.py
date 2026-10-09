import sys
import time
from pathlib import Path

import pytest

from quarry.agent import transpile
from quarry.agent.transpile import CommandTranspiler, NoopTranspiler, default_transpiler


def test_noop_accepts_anything() -> None:
    assert NoopTranspiler().check("not even code") is None


def test_command_transpiler_reports_stderr_on_failure() -> None:
    ok = CommandTranspiler([sys.executable, "-c", "import sys; sys.stdin.read()"])
    assert ok.check("x") is None
    bad = CommandTranspiler(
        [sys.executable, "-c", "import sys; sys.stderr.write('syntax error at 1:3'); sys.exit(1)"]
    )
    assert bad.check("x") == "syntax error at 1:3"


def test_command_transpiler_gives_up_on_a_check_that_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transpile, "CHECK_TIMEOUT_SECONDS", 0.2)
    hangs = CommandTranspiler([sys.executable, "-c", "import time; time.sleep(30)"])
    began = time.monotonic()
    assert hangs.check("x") == "transpile check timed out after 0.2 s"
    assert time.monotonic() - began < 10


def test_default_transpiler_is_noop_without_bundle(tmp_path: Path) -> None:
    assert isinstance(default_transpiler(tmp_path), NoopTranspiler)
