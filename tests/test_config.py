import os
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from quarry.config import (
    CONFIG_FILENAME,
    ConfigError,
    DataConfig,
    LibrariesConfig,
    QuarryConfig,
    api_key,
    load_config,
)

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
    assert cfg.provider.model == "claude-opus-5-5"
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
    assert cfg.provider.api_key_file == Path.home() / ".quarry/anthropic.key"
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


def write_key_file(path: Path, text: str = "sk-file\n", mode: int = 0o600) -> Path:
    path.write_text(text)
    os.chmod(path, mode)
    return path


def config_for_key_file(root: Path, key_file: Path) -> QuarryConfig:
    (root / "config.toml").write_text(f'[provider]\napi_key_file = "{key_file}"\n')
    return load_config(root, env={})


def test_api_key_for_openai_reads_its_own_variable(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[provider]\nname = "openai"\n')
    cfg = load_config(tmp_path, env={})
    env = {"QUARRY_ANTHROPIC_API_KEY": "sk-anthropic", "QUARRY_OPENAI_API_KEY": "sk-openai"}
    assert api_key(cfg, env=env) == "sk-openai"


def test_openai_without_its_variable_names_it(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[provider]\nname = "openai"\n')
    cfg = load_config(tmp_path, env={})
    with pytest.raises(ConfigError, match="QUARRY_OPENAI_API_KEY"):
        api_key(cfg, env={"QUARRY_ANTHROPIC_API_KEY": "sk-anthropic"})


def test_api_key_env_beats_the_key_file(tmp_path: Path) -> None:
    cfg = config_for_key_file(tmp_path, write_key_file(tmp_path / "anthropic.key"))
    assert api_key(cfg, env={"QUARRY_ANTHROPIC_API_KEY": "sk-env"}) == "sk-env"


def test_api_key_refuses_world_readable_file(tmp_path: Path) -> None:
    cfg = config_for_key_file(tmp_path, write_key_file(tmp_path / "anthropic.key", mode=0o604))
    with pytest.raises(ConfigError, match="permissions"):
        api_key(cfg, env={})


def test_api_key_missing_file_raises_config_error(tmp_path: Path) -> None:
    cfg = config_for_key_file(tmp_path, tmp_path / "absent.key")
    with pytest.raises(ConfigError, match="not found"):
        api_key(cfg, env={})


def test_api_key_empty_file_raises_config_error(tmp_path: Path) -> None:
    cfg = config_for_key_file(tmp_path, write_key_file(tmp_path / "anthropic.key", "  \n"))
    with pytest.raises(ConfigError, match="empty"):
        api_key(cfg, env={})


def test_api_key_directory_raises_config_error(tmp_path: Path) -> None:
    key_dir = tmp_path / "anthropic.key"
    key_dir.mkdir()
    cfg = config_for_key_file(tmp_path, key_dir)
    with pytest.raises(ConfigError, match=re.escape(str(key_dir))):
        api_key(cfg, env={})


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_api_key_unreadable_file_raises_config_error(tmp_path: Path) -> None:
    key_file = write_key_file(tmp_path / "anthropic.key", mode=0o000)
    cfg = config_for_key_file(tmp_path, key_file)
    with pytest.raises(ConfigError, match=re.escape(str(key_file))):
        api_key(cfg, env={})


def test_api_key_undecodable_file_raises_config_error(tmp_path: Path) -> None:
    key_file = tmp_path / "anthropic.key"
    key_file.write_bytes(b"sk-\xff\xfe")
    os.chmod(key_file, 0o600)
    cfg = config_for_key_file(tmp_path, key_file)
    with pytest.raises(ConfigError, match=re.escape(str(key_file))) as caught:
        api_key(cfg, env={})
    # Not chained: a traceback would print the offending key bytes.
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


def test_root_key_in_config_file_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('root = "/elsewhere"\n')
    with pytest.raises(ConfigError, match="cannot set root; pass --root instead"):
        load_config(tmp_path, env={})


SECRET = "hunter2-secret"


@pytest.mark.parametrize(
    "text",
    [
        f'[data]\nmssql_dns = "Server=db;PWD={SECRET}"\n',
        f'[data]\nmssql_dsn = ["Server=db;PWD={SECRET}"]\n',
        f'[libraries]\nhighcharts_license = ["{SECRET}"]\n',
        f'[libraries]\nscichart_license = {{ key = "{SECRET}" }}\n',
        f'[data]\nrow_cap = "{SECRET}"\n',
    ],
    ids=[
        "misspelled_dsn",
        "wrong_type_dsn",
        "wrong_type_highcharts",
        "wrong_type_scichart",
        "bad_cap",
    ],
)
def test_validation_errors_do_not_echo_the_input(text: str, tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(text)
    with pytest.raises(ValidationError) as caught:
        load_config(tmp_path, env={})
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)


def test_repr_hides_the_secrets(tmp_path: Path) -> None:
    cfg = QuarryConfig(
        root=tmp_path,
        data=DataConfig(mssql_dsn=f"Server=db;PWD={SECRET}"),
        libraries=LibrariesConfig(
            highcharts_license=f"{SECRET}-highcharts", scichart_license=f"{SECRET}-scichart"
        ),
    )
    assert SECRET not in repr(cfg)
    assert SECRET not in str(cfg)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_paths_expand_the_home_directory(home: Path, tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        '[provider]\napi_key_file = "~/k"\n'
        '[data]\nparquet_root = "~/cache"\n'
        '[libraries]\nteam_components = "~/team"\n'
        'highcharts_path = "~/hc"\nscichart_path = "~/sci"\n'
    )
    cfg = load_config(tmp_path, env={})
    assert cfg.provider.api_key_file == home / "k"
    assert cfg.data.parquet_root == home / "cache"
    assert cfg.libraries.team_components == home / "team"
    assert cfg.libraries.highcharts_path == home / "hc"
    assert cfg.libraries.scichart_path == home / "sci"


def test_relative_paths_resolve_against_the_root_not_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    (root / "config.toml").write_text(
        '[provider]\napi_key_file = "keys/k"\n'
        '[data]\nparquet_root = "cache"\n'
        '[libraries]\nteam_components = "team"\n'
        'highcharts_path = "lib/hc"\nscichart_path = "/abs/sci"\n'
    )
    cfg = load_config(root, env={})
    assert cfg.provider.api_key_file == root / "keys/k"
    assert cfg.data.parquet_root == root / "cache"
    assert cfg.libraries.team_components == root / "team"
    assert cfg.libraries.highcharts_path == root / "lib/hc"
    assert cfg.libraries.scichart_path == Path("/abs/sci")


def test_root_expands_the_home_directory(home: Path) -> None:
    root = home / "x"
    root.mkdir()
    (root / "config.toml").write_text('[data]\nparquet_root = "cache"\nrow_cap = 7\n')
    cfg = load_config(Path("~/x"), env={})
    assert cfg.root == root
    assert cfg.data.row_cap == 7
    assert cfg.data.parquet_root == root / "cache"


def test_api_key_reads_a_key_file_under_the_home_directory(home: Path, tmp_path: Path) -> None:
    write_key_file(home / "k", "sk-home\n")
    (tmp_path / "config.toml").write_text('[provider]\napi_key_file = "~/k"\n')
    assert api_key(load_config(tmp_path, env={}), env={}) == "sk-home"


def test_relative_root_becomes_absolute_and_revalidation_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "config.toml").write_text('[data]\nparquet_root = "cache"\n')
    cfg = load_config(Path("sub"), env={})
    assert cfg.root == Path.cwd() / "sub"
    assert cfg.data.parquet_root == Path.cwd() / "sub" / "cache"
    # A dumped config validated again must not prefix the root a second time.
    assert QuarryConfig.model_validate(cfg.model_dump()) == cfg


NO_SUCH_USER = "~quarry-no-such-user"


def test_root_with_an_unknown_user_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match=NO_SUCH_USER):
        load_config(Path(f"{NO_SUCH_USER}/x"), env={})


@pytest.mark.parametrize(
    "section_and_key",
    [
        "provider.api_key_file",
        "data.parquet_root",
        "libraries.team_components",
        "libraries.highcharts_path",
        "libraries.scichart_path",
    ],
)
def test_path_with_an_unknown_user_is_a_config_error(section_and_key: str, tmp_path: Path) -> None:
    section, key = section_and_key.split(".")
    (tmp_path / "config.toml").write_text(f'[{section}]\n{key} = "{NO_SUCH_USER}/p"\n')
    with pytest.raises(ConfigError, match=NO_SUCH_USER):
        load_config(tmp_path, env={})
