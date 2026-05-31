import subprocess

import yaml

from .conftest import snapshot_count


def _make_config(path, log_dir, repo, password, source, fix_homes=None):
    config = {
        "run-backup": {"log-path": str(log_dir)},
        "profiles": {
            "common": {
                "repository": str(repo),
                "env": {"RESTIC_PASSWORD": password},
            },
            "p1": {
                "inherit": "common",
                "backup": {"source": [str(source)]},
            },
        },
    }
    if fix_homes is not None:
        config["fix-homes"] = fix_homes
    path.write_text(yaml.safe_dump(config, default_flow_style=False))
    return path


def test_orchestrates_backup(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, test_env
):
    (fake_home / "doc.txt").write_text("hello\n")
    log_dir = tmp_path / "logs"
    config = _make_config(tmp_path / "rip.yaml", log_dir, restic_repo, restic_password, fake_home)

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    log_files = list(log_dir.iterdir())
    assert len(log_files) == 1
    assert "Backing up profile p1" in log_files[0].read_text()
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_aborts_when_fix_home_strict_fails(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, current_user, test_env
):
    (fake_home / ".dotfiles").mkdir()
    (fake_home / ".vimrc").write_text("set nu\n")

    log_dir = tmp_path / "logs"
    config = _make_config(
        tmp_path / "rip.yaml", log_dir, restic_repo, restic_password, fake_home,
        fix_homes={current_user: {"ignore": [".dotfiles"], ".dotfiles": [".vimrc"]}},
    )

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0


def test_proceeds_when_fix_home_strict_passes(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, current_user, test_env
):
    (fake_home / ".dotfiles").mkdir()
    (fake_home / ".dotfiles" / ".vimrc").write_text("set nu\n")
    (fake_home / ".vimrc").symlink_to(".dotfiles/.vimrc")
    (fake_home / "doc.txt").write_text("hello\n")

    log_dir = tmp_path / "logs"
    config = _make_config(
        tmp_path / "rip.yaml", log_dir, restic_repo, restic_password, fake_home,
        fix_homes={current_user: {"ignore": [".dotfiles"], ".dotfiles": [".vimrc"]}},
    )

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1
