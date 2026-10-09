"""Quarry configuration: TOML file under the root plus environment overrides."""

from __future__ import annotations

import os
import re
import stat
import tomllib
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Final, Literal, Self, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

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
_Section = TypeVar("_Section", bound=BaseModel)


# Every model forbids unknown keys: a misspelled `kernel_memorry_mb` would otherwise be
# dropped silently, leaving the kernel uncapped. A validation error never echoes its input,
# which may be a DSN password or a license key.
class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ProviderConfig(_Model):
    name: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-opus-5-5"
    api_key_file: OptionalPath = None


class DataConfig(_Model):
    parquet_root: OptionalPath = None
    mssql_dsn: str = Field(default="", repr=False)
    row_cap: int = Field(default=50000, ge=1)
    kernel_memory_mb: int = Field(default=0, ge=0)  # 0 = unlimited


class LibrariesConfig(_Model):
    team_components: OptionalPath = None
    highcharts_license: str = Field(default="", repr=False)
    highcharts_path: OptionalPath = None
    scichart_license: str = Field(default="", repr=False)
    scichart_path: OptionalPath = None


class QuarryConfig(_Model):
    root: Path
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    libraries: LibrariesConfig = Field(default_factory=LibrariesConfig)

    @model_validator(mode="after")
    def _anchor_paths(self) -> Self:
        # The server and each kernel may run from different working directories, so every
        # path field becomes absolute here: `~` expanded, a relative path taken from the root.
        self.root = self.root.expanduser()
        self.provider = _anchored(self.provider, self.root)
        self.data = _anchored(self.data, self.root)
        self.libraries = _anchored(self.libraries, self.root)
        return self


def _anchored(section: _Section, root: Path) -> _Section:
    paths = {name: root / value.expanduser() for name, value in section if isinstance(value, Path)}
    return section.model_copy(update=paths)


def load_config(root: Path, env: Mapping[str, str] | None = None) -> QuarryConfig:
    environment = os.environ if env is None else env
    root = root.expanduser()
    path = root / CONFIG_FILENAME
    raw: dict[str, object] = {}
    if path.exists():
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    # Only --root sets the root: a config key would redirect every root-relative resource.
    if "root" in raw:
        raise ConfigError("config.toml cannot set root; pass --root instead")
    config = QuarryConfig.model_validate({"root": root, **raw})
    # Before the environment's DSN replaces it: the file's permissions expose only its own.
    if _DSN_PASSWORD.search(config.data.mssql_dsn) and _group_or_world(path.stat()):
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
    return _read_owner_only(key_file)


def _read_owner_only(path: Path) -> str:
    # One open file: the permissions checked are those of the bytes read.
    try:
        with path.open(encoding="utf-8") as handle:
            if _group_or_world(os.fstat(handle.fileno())):
                raise ConfigError(
                    f"API key file {path} has group or world permissions; use chmod 600"
                )
            key = handle.read().strip()
    except FileNotFoundError:
        raise ConfigError(f"API key file not found: {path}") from None
    except OSError as error:
        raise ConfigError(f"API key file unreadable: {path}: {error.strerror}") from error
    except UnicodeDecodeError:
        # `from None`: the error's text quotes a byte of the key.
        raise ConfigError(f"API key file is not valid UTF-8: {path}") from None
    if not key:
        raise ConfigError(f"API key file is empty: {path}")
    return key


def _group_or_world(status: os.stat_result) -> bool:
    return bool(stat.S_IMODE(status.st_mode) & (stat.S_IRWXG | stat.S_IRWXO))
