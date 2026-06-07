import subprocess

from .conftest import snapshot_count


def _config_dict(log_dir, repo, password, source, fix_homes=None):
    config = {
        "log-path": str(log_dir),
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
        [rip_bin, "--config", str(config), "backup"],
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
    # Seed two pre-existing snapshots; backup will create a third, then
    # forget keep-last=1 should leave only the newest.
    (fake_home / "doc.txt").write_text("v1\n")
    log_dir = tmp_path / "logs"
    config_path = write_config({
        "log-path": str(log_dir),
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
            [rip_bin, "--config", str(config_path), "restic", "backup", "p1"],
            capture_output=True, text=True, env=test_env, check=True,
        )
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 2

    (fake_home / "doc.txt").write_text("v3\n")
    result = subprocess.run(
        [rip_bin, "--config", str(config_path), "backup"],
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
        [rip_bin, "--config", str(config), "backup", "--dry-run"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    run_dir = next(iter(log_dir.iterdir()))
    log_content = (run_dir / "backup.log").read_text()
    # In --dry-run mode the pre-pass IS the dry-run; we don't re-spawn restic.
    assert "Backing up profile p1" in log_content
    assert "Dry-run pre-pass for p1" in log_content
    assert "dry-run scan complete" in log_content
    assert "dry-run OK" in log_content                  # in the summary
    assert "no errors were found" not in log_content   # check skipped
    # And no snapshot was actually created.
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0


def test_size_limit_skips_profile_in_backup(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # Big source + 1KB limit → diagnostic pre-pass sees too much, profile is
    # skipped, no restic backup is ever invoked, no snapshot lands.
    (fake_home / "big.bin").write_bytes(b"x" * 50_000)
    log_dir = tmp_path / "logs"
    config = write_config({
        "added-size-limit": "1KB",
        "log-path": str(log_dir),
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

    result = subprocess.run(
        [rip_bin, "--config", str(config), "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0  # summary reports a failure row
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0
    run_dir = next(iter(log_dir.iterdir()))
    log = (run_dir / "backup.log").read_text()
    assert "exceeds added-size-limit" in log
    assert "ncdu --apparent-size -f" in log
    assert "size-limit exceeded" in log


def test_ignore_added_size_limit_bypasses_the_gate(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # Same setup as test_size_limit_skips_profile_in_backup, but
    # --ignore-added-size-limit lets the profile through.
    (fake_home / "big.bin").write_bytes(b"x" * 50_000)
    log_dir = tmp_path / "logs"
    config = write_config({
        "added-size-limit": "1KB",
        "log-path": str(log_dir),
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

    result = subprocess.run(
        [rip_bin, "--config", str(config), "backup", "--ignore-added-size-limit"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_only_filters_profiles_by_name(
    fake_home, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # Two profiles, each pointing at its own repo. Only the one named in
    # --only should be backed up.
    import os as _os
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    for r in (repo_a, repo_b):
        subprocess.run(
            [restic_bin, "init", "--repo", str(r)],
            env={**_os.environ, "RESTIC_PASSWORD": restic_password},
            check=True, capture_output=True,
        )
    (fake_home / "doc.txt").write_text("hi\n")
    log_dir = tmp_path / "logs"

    config = write_config({
        "log-path": str(log_dir),
        "profiles": {
            "common": {"env": {"RESTIC_PASSWORD": restic_password}},
            "alpha": {
                "inherit": "common",
                "repository": str(repo_a),
                "backup": {"source": [str(fake_home)]},
            },
            "beta": {
                "inherit": "common",
                "repository": str(repo_b),
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "backup", "--only", "alpha"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    assert snapshot_count(restic_bin, repo_a, restic_password) == 1
    assert snapshot_count(restic_bin, repo_b, restic_password) == 0


def test_only_unknown_profile_fails_loudly(
    fake_home, restic_password, tmp_path, rip_bin, write_config, test_env
):
    config = write_config({
        "profiles": {
            "common": {
                "repository": "/x",
                "env": {"RESTIC_PASSWORD": restic_password},
            },
            "alpha": {
                "inherit": "common",
                "backup": {"source": [str(fake_home)]},
            },
        },
    })
    result = subprocess.run(
        [rip_bin, "--config", str(config), "backup", "--only", "nope"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0
    assert "nope" in (result.stdout + result.stderr)


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
        [rip_bin, "--config", str(config), "backup", "--log-path", str(log_dir)],
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
        # no backup section at all
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Backing up profile p1" in result.stderr
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_fix_home_failure_aborts_backup(
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
        [rip_bin, "--config", str(config), "backup"],
        capture_output=True, text=True, env=test_env,
    )
    # fix-home failed → backup aborts before any backup runs.
    assert result.returncode != 0
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0

    run_dir = next(iter(log_dir.iterdir()))
    log = (run_dir / "backup.log").read_text()
    assert "Aborting: fix-home reported pending actions" in log
    assert f"fix-home/{current_user}" in log and "failed" in log
    # Profile loop never ran.
    assert "Backing up profile" not in log


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
        "log-path": str(log_dir),
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
        [rip_bin, "--config", str(config), "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0  # because `bad` failed
    assert snapshot_count(restic_bin, good_repo, restic_password) == 1

    run_dir = next(iter(log_dir.iterdir()))
    log = (run_dir / "backup.log").read_text()
    assert "=== Summary ===" in log
    assert "bad" in log and "failed" in log
    assert "good" in log and "OK" in log


def test_desktop_notifications_invoke_notify_send(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # Stub `notify-send` on PATH that appends its argv to a log file. With
    # desktop-notifications: true the run should write at least a "start"
    # and a "finished" notification.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    notify_log = tmp_path / "notify.log"
    stub = bin_dir / "notify-send"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> {notify_log}\n')
    stub.chmod(0o755)

    (fake_home / "doc.txt").write_text("hi\n")
    log_dir = tmp_path / "logs"
    config = write_config({
        **_config_dict(log_dir, restic_repo, restic_password, fake_home),
        "desktop-notifications": True,
    })

    env = {**test_env, "PATH": f"{bin_dir}:{test_env['PATH']}"}
    result = subprocess.run(
        [rip_bin, "--config", str(config), "backup"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    invocations = notify_log.read_text()
    assert "Backup started" in invocations
    assert "Backup finished" in invocations


def _freq_config(log_dir, repo, password, source):
    """Same shape as _config_dict but every profile has tag matching its name —
    the requirement when `frequency` is set."""
    return {
        "log-path": str(log_dir),
        "profiles": {
            "common": {
                "repository": str(repo),
                "env": {"RESTIC_PASSWORD": password},
            },
            "p1": {
                "inherit": "common",
                "backup": {"source": [str(source)], "tag": "p1"},
            },
        },
    }


def test_frequency_skips_recent_profile(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # Run a backup once → second invocation with a generous frequency should
    # skip without creating a new snapshot.
    (fake_home / "doc.txt").write_text("hi\n")
    log_dir = tmp_path / "logs"

    # First run: no frequency, single snapshot lands.
    config_no_freq = write_config(_freq_config(log_dir, restic_repo, restic_password, fake_home))
    r1 = subprocess.run(
        [rip_bin, "--config", str(config_no_freq), "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert r1.returncode == 0, f"stdout: {r1.stdout}\nstderr: {r1.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1

    # Second run: same config but with frequency=1w. The fresh snapshot is
    # well within the window, so we expect skip + no new snapshot.
    log_dir2 = tmp_path / "logs2"
    config_with_freq = write_config({
        **_freq_config(log_dir2, restic_repo, restic_password, fake_home),
        "frequency": "1w",
    })
    r2 = subprocess.run(
        [rip_bin, "--config", str(config_with_freq), "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert r2.returncode == 0, f"stdout: {r2.stdout}\nstderr: {r2.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1
    log = (next(log_dir2.iterdir()) / "backup.log").read_text()
    assert "up-to-date" in log


def test_frequency_runs_when_no_prior_snapshot(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # Frequency gates only fire after the first snapshot exists. Empty repo →
    # backup must run.
    (fake_home / "doc.txt").write_text("hi\n")
    log_dir = tmp_path / "logs"
    config = write_config({
        **_freq_config(log_dir, restic_repo, restic_password, fake_home),
        "frequency": "1w",
    })

    r = subprocess.run(
        [rip_bin, "--config", str(config), "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert r.returncode == 0, f"stdout: {r.stdout}\nstderr: {r.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_ignore_frequency_bypasses_the_gate(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # First run lands a snapshot, second run uses --ignore-frequency and the
    # snapshot count must grow to 2 despite the recent prior backup.
    (fake_home / "doc.txt").write_text("hi\n")
    log_dir = tmp_path / "logs"
    config = write_config({
        **_freq_config(log_dir, restic_repo, restic_password, fake_home),
        "frequency": "1w",
    })

    subprocess.run(
        [rip_bin, "--config", str(config), "backup", "--ignore-frequency"],
        capture_output=True, text=True, env=test_env, check=True,
    )
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1

    # New data + --ignore-frequency → new snapshot.
    (fake_home / "doc.txt").write_text("hi2\n")
    log_dir2 = tmp_path / "logs2"
    config2 = write_config({
        **_freq_config(log_dir2, restic_repo, restic_password, fake_home),
        "frequency": "1w",
    })
    subprocess.run(
        [rip_bin, "--config", str(config2), "backup", "--ignore-frequency"],
        capture_output=True, text=True, env=test_env, check=True,
    )
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 2


def test_all_up_to_date_suppresses_finished_notification(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, write_config, test_env
):
    # When every profile is up-to-date, we still want exit 0 — but no
    # "Backup finished" desktop notification, just silence.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    notify_log = tmp_path / "notify.log"
    stub = bin_dir / "notify-send"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> {notify_log}\n')
    stub.chmod(0o755)
    env = {**test_env, "PATH": f"{bin_dir}:{test_env['PATH']}"}

    (fake_home / "doc.txt").write_text("hi\n")
    log_dir = tmp_path / "logs"

    # First run lands a snapshot (no frequency, no skip).
    config_init = write_config({
        **_freq_config(log_dir, restic_repo, restic_password, fake_home),
        "desktop-notifications": True,
    })
    subprocess.run(
        [rip_bin, "--config", str(config_init), "backup"],
        capture_output=True, text=True, env=env, check=True,
    )
    notify_log.write_text("")  # reset to only capture the second run

    # Second run: frequency=1w; everything is up-to-date.
    log_dir2 = tmp_path / "logs2"
    config_gated = write_config({
        **_freq_config(log_dir2, restic_repo, restic_password, fake_home),
        "frequency": "1w",
        "desktop-notifications": True,
    })
    r = subprocess.run(
        [rip_bin, "--config", str(config_gated), "backup"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"stdout: {r.stdout}\nstderr: {r.stderr}"
    invocations = notify_log.read_text()
    # Started fires (we don't know up front there's no work), Finished does not.
    assert "Backup finished" not in invocations
