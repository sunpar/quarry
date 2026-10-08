import os
from pathlib import Path

import pytest

from quarry.config import ConfigError, QuarryConfig, api_key, load_config


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


def test_env_overrides_mssql_dsn(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[data]\nmssql_dsn = "file-dsn"\n')
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
