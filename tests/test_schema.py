from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from restic_in_peace import profile


def _write(tmp_path: Path, config: Any) -> str:
    path = tmp_path / "rip.yaml"
    path.write_text(yaml.safe_dump(config))
    return str(path)


def test_full_config_validates(tmp_path: Path) -> None:
    config = {
        "profiles": {
            "common": {
                "repository": "/backup",
                "env": {"RESTIC_PASSWORD": "x"},
                "added-size-limit": "5GB",
                "skip-on-battery": True,
                "wifi-whitelist": ["home-net"],
                "monitor-url": ["https://m.example/restic"],
            },
            "laptop": {
                "inherit": "common",
                "backup": {"source": ["/home/me"], "tag": "laptop"},
                "forget": {"keep-daily": 7, "keep-weekly": 4, "prune": False},
            },
        },
        "fix-homes": {
            "me": {"ignore": [".cache"], ".dotfiles": [".vimrc", ".bashrc"]},
        },
        "run-backup": {"log-path": "/var/log/rip"},
    }
    path = _write(tmp_path, config)
    loaded = profile.load_config(path)
    assert loaded == config


def test_empty_file_validates(tmp_path: Path) -> None:
    path = tmp_path / "rip.yaml"
    path.write_text("")
    assert profile.load_config(str(path)) == {}


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, {"profiles": {}, "garbage": 1})
    with pytest.raises(profile.ConfigError, match="garbage|additional"):
        profile.load_config(path)


def test_run_backup_requires_log_path(tmp_path: Path) -> None:
    path = _write(tmp_path, {"run-backup": {}})
    with pytest.raises(profile.ConfigError, match="log-path"):
        profile.load_config(path)


def test_fix_home_value_must_be_list_of_strings(tmp_path: Path) -> None:
    path = _write(tmp_path, {"fix-homes": {"alice": {".dotfiles": "not-a-list"}}})
    with pytest.raises(profile.ConfigError):
        profile.load_config(path)


def test_profile_inherit_must_be_string(tmp_path: Path) -> None:
    path = _write(tmp_path, {"profiles": {"p1": {"inherit": 42}}})
    with pytest.raises(profile.ConfigError, match="inherit"):
        profile.load_config(path)


def test_skip_on_battery_must_be_bool(tmp_path: Path) -> None:
    path = _write(tmp_path, {"profiles": {"p1": {"skip-on-battery": "yes"}}})
    with pytest.raises(profile.ConfigError, match="skip-on-battery"):
        profile.load_config(path)


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "rip.yaml"
    path.write_text("not: valid: yaml: [")
    with pytest.raises(profile.ConfigError, match="YAML"):
        profile.load_config(str(path))


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(profile.ConfigError, match="not found"):
        profile.load_config(str(tmp_path / "missing.yaml"))


def test_resticprofile_retention_section_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, {
        "profiles": {
            "p1": {
                "repository": "/x",
                "env": {"RESTIC_PASSWORD": "y"},
                "retention": {"keep-daily": 7, "prune": False},
            },
        },
    })
    with pytest.raises(profile.ConfigError, match="retention"):
        profile.load_config(path)


def test_typo_in_restic_flag_rejected(tmp_path: Path) -> None:
    # `repsitory` is a typo of `repository` (and not a real restic flag).
    path = _write(tmp_path, {"profiles": {"p1": {"repsitory": "/x"}}})
    with pytest.raises(profile.ConfigError, match="repsitory"):
        profile.load_config(path)


def test_resolve_drops_stray_subsection_even_if_schema_permissive() -> None:
    # Defensive: if the snapshot were ever absent the schema falls back to
    # permissive; resolve() still drops stray dict-valued sub-sections so
    # they cannot be translated to a restic flag.
    settings, _ = profile.resolve(
        {"profiles": {"p1": {"repository": "/x", "retention": {"keep-daily": 7}}}},
        "p1", "ls",
    )
    assert "retention" not in settings


def test_rip_sample_yaml_validates() -> None:
    # The shipped sample must validate, otherwise it lies about the schema.
    here = Path(__file__).resolve().parents[1]
    sample = here / "rip.sample.yaml"
    if sample.exists():
        profile.load_config(str(sample))
