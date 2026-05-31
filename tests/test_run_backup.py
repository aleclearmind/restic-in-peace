import subprocess

from .conftest import snapshot_count


def _config_dict(log_dir, repo, password, source, fix_homes=None):
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
    return config


def test_orchestrates_backup(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    (fake_home / "doc.txt").write_text("hello\n")
    log_dir = tmp_path / "logs"
    config = write_config(_config_dict(log_dir, restic_repo, restic_password, fake_home))

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    log_files = list(log_dir.iterdir())
    assert len(log_files) == 1
    log_content = log_files[0].read_text()
    assert "Backing up profile p1" in log_content
    assert "no errors were found" in log_content or "check" in log_content
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_runs_forget_when_section_present(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # Seed two pre-existing snapshots; run-backup will create a third, then
    # forget keep-last=1 should leave only the newest.
    (fake_home / "doc.txt").write_text("v1\n")
    log_dir = tmp_path / "logs"
    config_path = write_config({
        "run-backup": {"log-path": str(log_dir)},
        "profiles": {
            "common": {
                "repository": str(restic_repo),
                "env": {"RESTIC_PASSWORD": restic_password},
            },
            "p1": {
                "inherit": "common",
                "backup": {"source": [str(fake_home)]},
                "forget": {"keep-last": 1},
            },
        },
    })

    for content in ("v1\n", "v2\n"):
        (fake_home / "doc.txt").write_text(content)
        subprocess.run(
            [rip_bin, "--config", str(config_path), "--name", "p1", "backup"],
            capture_output=True, text=True, env=test_env, check=True,
        )
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 2

    (fake_home / "doc.txt").write_text("v3\n")
    result = subprocess.run(
        [rip_bin, "run-backup", str(config_path)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_aborts_when_fix_home_strict_fails(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, current_user, write_config, test_env
):
    (fake_home / ".dotfiles").mkdir()
    (fake_home / ".vimrc").write_text("set nu\n")

    log_dir = tmp_path / "logs"
    config = write_config(_config_dict(
        log_dir, restic_repo, restic_password, fake_home,
        fix_homes={current_user: {"ignore": [".dotfiles"], ".dotfiles": [".vimrc"]}},
    ))

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0


def test_proceeds_when_fix_home_strict_passes(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, current_user, write_config, test_env
):
    (fake_home / ".dotfiles").mkdir()
    (fake_home / ".dotfiles" / ".vimrc").write_text("set nu\n")
    (fake_home / ".vimrc").symlink_to(".dotfiles/.vimrc")
    (fake_home / "doc.txt").write_text("hello\n")

    log_dir = tmp_path / "logs"
    config = write_config(_config_dict(
        log_dir, restic_repo, restic_password, fake_home,
        fix_homes={current_user: {"ignore": [".dotfiles"], ".dotfiles": [".vimrc"]}},
    ))

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1
