"""Opt-in licensed chart libraries: which are usable, and the file the runtime loads."""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, Field

from quarry.config import QuarryConfig

LibraryId = Literal["highcharts", "scichart"]
# The file the runtime loads from the mounted package. Highcharts is a classic UMD script that
# sets window.Highcharts; SciChart is a self-contained ES module with its wasm under _wasm/.
ENTRIES: Final[dict[LibraryId, str]] = {
    "highcharts": "highstock.js",
    "scichart": "index.min.mjs",
}


class LibraryStatus(BaseModel):
    id: LibraryId
    enabled: bool
    reason: str | None = None
    # Sent to the browser, which hands it to the library at load time; never logged.
    license: str | None = Field(default=None, repr=False)
    entry: str | None = None


def licensed_libraries(config: QuarryConfig) -> list[LibraryStatus]:
    """One status per licensed library, enabled only with a key and an installed package."""
    return [_status(library, config) for library in ENTRIES]


def library_settings(library: LibraryId, config: QuarryConfig) -> tuple[str, Path | None]:
    """The library's license key and install path from the config."""
    key: str = getattr(config.libraries, f"{library}_license")
    path: Path | None = getattr(config.libraries, f"{library}_path")
    return key, path


def _status(library: LibraryId, config: QuarryConfig) -> LibraryStatus:
    key, path = library_settings(library, config)
    if not key:
        return LibraryStatus(id=library, enabled=False, reason=f"{library}_license is not set")
    entry = ENTRIES[library]
    if path is None:
        reason = f"{library}_path is not set"
    elif not (path / entry).is_file():
        reason = f"{library}_path {path} does not exist or lacks {entry}"
    else:
        return LibraryStatus(
            id=library, enabled=True, license=key, entry=f"/libs/{library}/{entry}"
        )
    return LibraryStatus(id=library, enabled=False, reason=reason)
