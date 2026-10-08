"""Quarry configuration: TOML file under the root plus environment overrides."""

from __future__ import annotations

import os
import re
import stat
import tomllib
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

CONFIG_FILENAME: Final = "config.toml"
ENV_MSSQL_DSN: Final = "QUARRY_MSSQL_DSN"
ENV_API_KEY: Final[dict[str, str]] = {
    "anthropic": "QUARRY_ANTHROPIC_API_KEY",
    "openai": "QUARRY_OPENAI_API_KEY",
}
# An ODBC PWD or Password key, at the start of a DSN or after a `;`.
_DSN_PASSWORD: Final = re.compile(r"(?:^|;)\s*(?:pwd|password)\s*=", re.IGNORECASE)


class ConfigError(Exception):
    """Raised for an unusable configuration."""


def _blank_to_none(value: object) -> object:
    # The documented config.toml writes "" for an unset path; pydantic would read it as Path(".").
    return None if value == "" else value


OptionalPath = Annotated[Path | None, BeforeValidator(_blank_to_none)]


# Every model forbids unknown keys: a misspelled `kernel_memorry_mb` would otherwise be
# dropped silently, leaving the kernel uncapped.
class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-sonnet-5-5"
    api_key_file: OptionalPath = None


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parquet_root: OptionalPath = None
    mssql_dsn: str = ""
    row_cap: int = Field(default=50000, ge=1)
    kernel_memory_mb: int = Field(default=0, ge=0)  # 0 = unlimited


class LibrariesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_components: OptionalPath = None
    highcharts_license: str = ""
    highcharts_path: OptionalPath = None
    scichart_license: str = ""
    scichart_path: OptionalPath = None


class QuarryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: Path
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    libraries: LibrariesConfig = Field(default_factory=LibrariesConfig)


def load_config(root: Path, env: Mapping[str, str] | None = None) -> QuarryConfig:
    environment = os.environ if env is None else env
    path = root / CONFIG_FILENAME
    raw: dict[str, object] = {}
    if path.exists():
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    config = QuarryConfig.model_validate({"root": root, **raw})
    # Before the environment's DSN replaces it: the file's permissions expose only its own.
    if _DSN_PASSWORD.search(config.data.mssql_dsn) and _group_or_world(path):
        warnings.warn(
            f"{path} holds a data.mssql_dsn password and has group or world permissions; "
            "use chmod 600",
            stacklevel=2,
        )
    dsn = environment.get(ENV_MSSQL_DSN)
    if dsn:
        config = config.model_copy(
            update={"data": config.data.model_copy(update={"mssql_dsn": dsn})}
        )
    return config


def api_key(config: QuarryConfig, env: Mapping[str, str] | None = None) -> str:
    environment = os.environ if env is None else env
    env_name = ENV_API_KEY[config.provider.name]
    from_env = environment.get(env_name)
    if from_env:
        return from_env
    key_file = config.provider.api_key_file
    if key_file is None:
        raise ConfigError(f"No API key: set {env_name} or provider.api_key_file")
    return _read_owner_only(key_file.expanduser())


def _read_owner_only(path: Path) -> str:
    if not path.exists():
        raise ConfigError(f"API key file not found: {path}")
    if _group_or_world(path):
        raise ConfigError(f"API key file {path} has group or world permissions; use chmod 600")
    key = path.read_text().strip()
    if not key:
        raise ConfigError(f"API key file is empty: {path}")
    return key


def _group_or_world(path: Path) -> bool:
    return bool(stat.S_IMODE(path.stat().st_mode) & (stat.S_IRWXG | stat.S_IRWXO))
