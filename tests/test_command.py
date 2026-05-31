from __future__ import annotations

import argparse

from restic_in_peace.utils.command import build_restic_command


def _args(**kwargs: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "repo": None,
        "password_file": None,
        "password_command": None,
        "verbose": None,
        "tag": None,
        "dry_run": False,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_boolean_flag_does_not_get_stringified_value() -> None:
    # Regression: isinstance(True, int) is True, so a bool used to fall into
    # the str/int branch and we'd emit `--dry-run True`. Restic then treats
    # "True" as a positional snapshot ID.
    cmd = build_restic_command(
        "forget",
        _args(dry_run=True),
        additional_argparse_arguments=["dry_run"],
    )
    assert "--dry-run" in cmd
    assert "True" not in cmd
    # Verify there isn't a trailing value where the bool flag is.
    idx = cmd.index("--dry-run")
    assert idx == len(cmd) - 1 or cmd[idx + 1].startswith("--")


def test_string_flag_passes_value() -> None:
    cmd = build_restic_command("snapshots", _args(repo="/some/repo"))
    i = cmd.index("--repo")
    assert cmd[i + 1] == "/some/repo"


def test_list_flag_joins_values() -> None:
    cmd = build_restic_command(
        "snapshots",
        _args(tag=["a", "b"]),
        additional_argparse_arguments=["tag"],
    )
    i = cmd.index("--tag")
    assert cmd[i + 1] == "a b"
