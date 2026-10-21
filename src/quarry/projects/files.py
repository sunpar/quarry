"""File helpers shared by the session and project stores."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

PRIVATE_DIR = 0o700
PRIVATE_FILE = 0o600


def child(parent: Path, name: str) -> Path:
    """`parent / name` for a name from a request: one path segment, so it cannot leave
    `parent`. Anything else is a KeyError, like a name with nothing behind it."""
    if name in ("", "..") or Path(name).name != name:
        raise KeyError(name)
    return parent / name


def write_atomic(path: Path, text: str) -> None:
    # A crash leaves at most a stray temp file, which the steps/*.json glob never matches.
    # Created private, never chmodded after, so it is not readable by others even briefly.
    try:
        fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            Path(temp).replace(path)
        finally:
            Path(temp).unlink(missing_ok=True)
    except OSError as exc:
        # Callers show this to users, who asked for `path`, not the temp file it would name.
        if exc.filename is None:
            raise
        raise OSError(exc.errno, exc.strerror, str(path)) from exc
    # The rename is durable only once the directory entry is.
    sync_dir(path.parent)


def sync_dir(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
