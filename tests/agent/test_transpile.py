import sys
from pathlib import Path

import pytest

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


def test_default_transpiler_is_noop_without_bundle(tmp_path: Path) -> None:
    assert isinstance(default_transpiler(tmp_path), NoopTranspiler)


STATIC = Path(__file__).resolve().parents[2] / "src" / "quarry" / "static"


@pytest.mark.skipif(not (STATIC / "transpile-check.mjs").exists(), reason="web build missing")
def test_default_transpiler_uses_bundle() -> None:
    checker = default_transpiler(STATIC)
    assert checker.check("export default () => <div/>") is None
    problem = checker.check("const a = (")
    assert problem is not None
    assert "Unexpected token" in problem
