"""Server-side syntax check for generated TSX, delegated to a node bundle when present."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Final, Protocol

log = logging.getLogger(__name__)

# A check that hangs would hold its step, and a restart waiting on that step, for good.
CHECK_TIMEOUT_SECONDS: Final = 30


class Transpiler(Protocol):
    def check(self, source: str) -> str | None: ...


class NoopTranspiler:
    def check(self, source: str) -> str | None:
        return None


class CommandTranspiler:
    def __init__(self, command: list[str]) -> None:
        self._command = command

    def check(self, source: str) -> str | None:
        try:
            done = subprocess.run(
                self._command,
                input=source,
                text=True,
                capture_output=True,
                check=False,
                timeout=CHECK_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:  # run() has killed the check by now
            return f"transpile check timed out after {CHECK_TIMEOUT_SECONDS} s"
        return (
            None
            if done.returncode == 0
            else (done.stderr.strip() or f"exit code {done.returncode}")
        )


def default_transpiler(static_dir: Path) -> Transpiler:
    bundle = static_dir / "transpile-check.mjs"
    if not bundle.exists():
        return NoopTranspiler()
    if shutil.which("node") is None:
        log.warning(
            "node is not on PATH, so generated views are not syntax-checked on the server; "
            "a broken view fails in the browser instead, where Fix this view repairs it"
        )
        return NoopTranspiler()
    return CommandTranspiler(["node", str(bundle)])
