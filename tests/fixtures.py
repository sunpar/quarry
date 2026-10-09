"""File-mode helpers for tests that make paths unreadable or check the modes Quarry creates."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

root_ignores_modes = pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")


@contextmanager
def chmodded(path: Path, bits: int) -> Iterator[None]:
    """`path` with mode `bits` inside the block, and its old mode back after."""
    previous = stat.S_IMODE(path.stat().st_mode)
    path.chmod(bits)
    try:
        yield
    finally:
        path.chmod(previous)


@contextmanager
def umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)
