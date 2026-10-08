import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from quarry.config import CONFIG_FILENAME, ConfigError, QuarryConfig, api_key, load_config

PASSWORD_DSN = "Driver={ODBC Driver 18 for SQL Server};Server=db;UID=me;PWD=hunter2"
TRUSTED_DSN = "Driver={ODBC Driver 18 for SQL Server};Server=db;Trusted_Connection=yes"


def write_dsn_config(root: Path, dsn: str, mode: int) -> None:
    path = root / CONFIG_FILENAME
    path.write_text(f'[data]\nmssql_dsn = "{dsn}"\n')
    os.chmod(path, mode)


def test_defaults_when_no_file(tmp_path: Path) -> None:
    cfg = load_config(tmp_path, env={})
    assert cfg.root == tmp_path
    assert cfg.provider.name == "anthropic"
    assert cfg.data.row_cap == 50000
    assert cfg.data.parquet_root is None


def test_reads_toml(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        '[provider]\nname = "openai"\nmodel = "gpt-5"\n'
        '[data]\nparquet_root = "/data/cache"\nrow_cap = 100\n'
    )
    cfg = load_config(tmp_path, env={})
    assert cfg.provider.name == "openai"
    assert cfg.provider.model == "gpt-5"
    assert cfg.data.parquet_root == Path("/data/cache")
    assert cfg.data.row_cap == 100


@pytest.mark.parametrize("row_cap", [0, -1])
def test_row_cap_below_one_is_rejected(row_cap: int, tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(f"[data]\nrow_cap = {row_cap}\n")
    with pytest.raises(ValidationError, match="row_cap"):
        load_config(tmp_path, env={})


def test_row_cap_of_one_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[data]\nrow_cap = 1\n")
    assert load_config(tmp_path, env={}).data.row_cap == 1


def test_negative_kernel_memory_mb_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[data]\nkernel_memory_mb = -1\n")
    with pytest.raises(ValidationError, match="kernel_memory_mb"):
        load_config(tmp_path, env={})


def test_kernel_memory_mb_of_zero_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[data]\nkernel_memory_mb = 0\n")
    assert load_config(tmp_path, env={}).data.kernel_memory_mb == 0


def test_env_overrides_mssql_dsn(tmp_path: Path) -> None:
    write_dsn_config(tmp_path, "file-dsn", 0o600)
    cfg = load_config(tmp_path, env={"QUARRY_MSSQL_DSN": "env-dsn"})
    assert cfg.data.mssql_dsn == "env-dsn"


def test_api_key_from_env(tmp_path: Path) -> None:
    cfg = load_config(tmp_path, env={})
    assert api_key(cfg, env={"QUARRY_ANTHROPIC_API_KEY": "sk-test"}) == "sk-test"


def test_api_key_from_owner_only_file(tmp_path: Path) -> None:
    key_file = tmp_path / "anthropic.key"
    key_file.write_text("sk-file\n")
    os.chmod(key_file, 0o600)
    (tmp_path / "config.toml").write_text(f'[provider]\napi_key_file = "{key_file}"\n')
    cfg = load_config(tmp_path, env={})
    assert api_key(cfg, env={}) == "sk-file"


def test_api_key_refuses_group_readable_file(tmp_path: Path) -> None:
    key_file = tmp_path / "anthropic.key"
    key_file.write_text("sk-file\n")
    os.chmod(key_file, 0o640)
    (tmp_path / "config.toml").write_text(f'[provider]\napi_key_file = "{key_file}"\n')
    cfg = load_config(tmp_path, env={})
    with pytest.raises(ConfigError, match="permissions"):
        api_key(cfg, env={})


def test_api_key_missing_raises(tmp_path: Path) -> None:
    cfg = QuarryConfig(root=tmp_path)
    with pytest.raises(ConfigError, match="QUARRY_ANTHROPIC_API_KEY"):
        api_key(cfg, env={})


def test_blank_paths_mean_unset(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        '[provider]\napi_key_file = ""\n'
        '[data]\nparquet_root = ""\n'
        '[libraries]\nteam_components = ""\nhighcharts_path = ""\nscichart_path = ""\n'
    )
    cfg = load_config(tmp_path, env={})
    assert cfg.provider.api_key_file is None
    assert cfg.data.parquet_root is None
    assert cfg.libraries.team_components is None
    assert cfg.libraries.highcharts_path is None
    assert cfg.libraries.scichart_path is None


@pytest.mark.parametrize(
    "dsn",
    [PASSWORD_DSN, "pwd=hunter2;Server=db", "Server=db; Password = hunter2"],
    ids=["after_semicolon", "at_start", "spaced_password"],
)
def test_warns_on_a_shared_config_holding_a_dsn_password(dsn: str, tmp_path: Path) -> None:
    write_dsn_config(tmp_path, dsn, 0o644)
    with pytest.warns(UserWarning, match="chmod 600"):
        load_config(tmp_path, env={})


@pytest.mark.filterwarnings("error")
@pytest.mark.parametrize(
    ("dsn", "mode"), [(PASSWORD_DSN, 0o600), (TRUSTED_DSN, 0o644)], ids=["owner_only", "no_pwd"]
)
def test_no_warning_without_both_a_password_and_shared_permissions(
    dsn: str, mode: int, tmp_path: Path
) -> None:
    write_dsn_config(tmp_path, dsn, mode)
    load_config(tmp_path, env={})


@pytest.mark.filterwarnings("error")
def test_no_warning_for_a_password_only_in_the_environment(tmp_path: Path) -> None:
    write_dsn_config(tmp_path, TRUSTED_DSN, 0o644)
    cfg = load_config(tmp_path, env={"QUARRY_MSSQL_DSN": PASSWORD_DSN})
    assert cfg.data.mssql_dsn == PASSWORD_DSN


# Spec §11's config.toml, every key with a value of its type.
SPEC_TEMPLATE = """
[provider]
name = "anthropic"
model = "claude-sonnet-5-5"
api_key_file = "~/.quarry/anthropic.key"

[data]
parquet_root = "/data/cache"
mssql_dsn = ""
row_cap = 50000
kernel_memory_mb = 0

[libraries]
team_components = ""
highcharts_license = ""
highcharts_path = ""
scichart_license = ""
scichart_path = ""
"""


def test_spec_template_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(SPEC_TEMPLATE)
    cfg = load_config(tmp_path, env={})
    assert cfg.provider.api_key_file == Path("~/.quarry/anthropic.key")
    assert cfg.data.parquet_root == Path("/data/cache")


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("[data]\nkernel_memorry_mb = 512\n", "kernel_memorry_mb"),
        ('[provider]\nmodle = "gpt-5"\n', "modle"),
        ('[libraries]\nhighchart_license = "x"\n', "highchart_license"),
        ("[ui]\ntheme = 1\n", "ui"),
    ],
    ids=["data_key", "provider_key", "libraries_key", "top_level_section"],
)
def test_unknown_keys_are_rejected(text: str, key: str, tmp_path: Path) -> None:
    # A misspelled key would otherwise be dropped silently, e.g. leaving the kernel uncapped.
    (tmp_path / "config.toml").write_text(text)
    with pytest.raises(ValidationError, match=key):
        load_config(tmp_path, env={})
