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

    # Exactly one dated sub-directory under log-path, holding the log and
    # a per-profile ncdu diagnostic.
    runs = sorted(log_dir.iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    assert run_dir.is_dir()
    log_file = run_dir / "backup.log"
    assert log_file.exists()
    log_content = log_file.read_text()
    assert "Backing up profile p1" in log_content
    assert "no errors were found" in log_content or "check" in log_content

    import json as _json
    diag = run_dir / "p1.ncdu.json"
    assert diag.exists()
    doc = _json.loads(diag.read_text())
    assert doc[0] == 1 and doc[1] == 2

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
            [rip_bin, "--config", str(config_path), "--name", "p1", "restic", "backup"],
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


def test_dry_run_skips_unlock_and_check_and_creates_no_snapshot(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    (fake_home / "doc.txt").write_text("hello\n")
    log_dir = tmp_path / "logs"
    config = write_config(_config_dict(log_dir, restic_repo, restic_password, fake_home))

    result = subprocess.run(
        [rip_bin, "run-backup", "--dry-run", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    run_dir = next(iter(log_dir.iterdir()))
    log_content = (run_dir / "backup.log").read_text()
    # backup ran (with --dry-run), unlock and check skipped.
    assert "Backing up profile p1" in log_content
    assert "restic backup" in log_content and "--dry-run" in log_content
    assert "restic unlock" not in log_content
    assert "restic check" not in log_content
    # And no snapshot was actually created.
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0


def test_log_path_cli_overrides_config(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    (fake_home / "doc.txt").write_text("hi\n")
    # Config has no log-path; the CLI flag supplies one.
    config = write_config({
        "profiles": {
            "common": {
                "repository": str(restic_repo),
                "env": {"RESTIC_PASSWORD": restic_password},
            },
            "p1": {
                "inherit": "common",
                "backup": {"source": [str(fake_home)]},
            },
        },
    })
    log_dir = tmp_path / "via-cli"

    result = subprocess.run(
        [rip_bin, "run-backup", "--log-path", str(log_dir), str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    runs = sorted(log_dir.iterdir())
    assert len(runs) == 1
    assert (runs[0] / "backup.log").exists()
    assert (runs[0] / "p1.ncdu.json").exists()


def test_falls_back_to_stderr_when_log_path_missing(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    (fake_home / "doc.txt").write_text("hello\n")
    config = write_config({
        "profiles": {
            "common": {
                "repository": str(restic_repo),
                "env": {"RESTIC_PASSWORD": restic_password},
            },
            "p1": {
                "inherit": "common",
                "backup": {"source": [str(fake_home)]},
            },
        },
        # no run-backup section at all
    })

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Backing up profile p1" in result.stderr
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_continues_after_fix_home_strict_fails(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, current_user, write_config, test_env
):
    # fix-home is in a state that --strict will report as needing action.
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
    # Overall exit is non-zero because fix-home reported a failure...
    assert result.returncode != 0
    # ...but the backup still ran (continue-on-failure) and produced a snapshot.
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1

    run_dir = next(iter(log_dir.iterdir()))
    log = (run_dir / "backup.log").read_text()
    assert "=== Summary ===" in log
    assert f"fix-home/{current_user}" in log and "failed" in log
    assert "p1" in log and "OK" in log


def test_continues_after_one_profile_fails(
    fake_home, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # One profile points at a bogus repo (the backup subcommand will fail);
    # the other points at a working repo and must still produce a snapshot.
    import os as _os
    good_repo = tmp_path / "good-repo"
    _os.makedirs(good_repo)
    subprocess.run(
        [restic_bin, "init", "--repo", str(good_repo)],
        env={**_os.environ, "RESTIC_PASSWORD": restic_password},
        check=True, capture_output=True,
    )
    (fake_home / "doc.txt").write_text("hi\n")
    log_dir = tmp_path / "logs"
    config = write_config({
        "run-backup": {"log-path": str(log_dir)},
        "profiles": {
            "common": {
                "env": {"RESTIC_PASSWORD": restic_password},
            },
            "bad": {
                "inherit": "common",
                "repository": "/nonexistent/bogus",
                "backup": {"source": [str(fake_home)]},
            },
            "good": {
                "inherit": "common",
                "repository": str(good_repo),
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "run-backup", str(config)],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0  # because `bad` failed
    assert snapshot_count(restic_bin, good_repo, restic_password) == 1

    run_dir = next(iter(log_dir.iterdir()))
    log = (run_dir / "backup.log").read_text()
    assert "=== Summary ===" in log
    assert "bad" in log and "failed" in log
    assert "good" in log and "OK" in log


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
