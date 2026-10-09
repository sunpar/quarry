"""Atomic text writes shared by the session and project stores."""

from __future__ import annotations

import os
from pathlib import Path

_PRIVATE_FILE = 0o600


def write_atomic(path: Path, text: str) -> None:
    # A crash leaves at most a stray temp file, which the steps/*.json glob never matches.
    temp = path.with_name(f".{path.name}.tmp")
    # Created private, never chmodded after, so it is not readable by others even briefly.
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)
    # The rename is durable only once the directory entry is.
    sync_dir(path.parent)


def sync_dir(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
