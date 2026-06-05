import subprocess

from .conftest import snapshot_count


def test_backup_creates_snapshot(
    fake_home, restic_repo, restic_password, rip_bin, restic_bin, test_env_with_password
):
    (fake_home / "doc.txt").write_text("hello world\n")

    result = subprocess.run(
        [rip_bin, "restic", "backup", "-r", str(restic_repo), str(fake_home)],
        capture_output=True, text=True, env=test_env_with_password,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_size_limit_aborts_backup(
    fake_home, restic_repo, restic_password, rip_bin, restic_bin, test_env_with_password
):
    (fake_home / "big.bin").write_bytes(b"x" * 10_000)

    result = subprocess.run(
        [
            rip_bin, "restic", "backup",
            "-r", str(restic_repo),
            "--added-size-limit", "1KB",
            str(fake_home),
        ],
        capture_output=True, text=True, env=test_env_with_password,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "the limit is" in combined and "aborting" in combined
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0


def test_size_limit_message_points_at_ncdu_diagnostic(
    fake_home, restic_repo, restic_password, rip_bin, restic_bin, tmp_path, test_env_with_password
):
    import json as _json
    (fake_home / "big.bin").write_bytes(b"x" * 10_000)
    # Simulate run-backup's env: a pre-written ncdu diagnostic the backup
    # pipeline should point the user at on size-limit abort. The diagnostic
    # lists one big file so significant_items reports it.
    diag = tmp_path / "p1.ncdu.json"
    diag.write_text(_json.dumps([
        1, 2, {"progname": "test", "progver": "0", "timestamp": 0},
        [{"name": "/"}, {"name": "big.bin", "asize": 10000, "dsize": 10000}],
    ]))
    env = {**test_env_with_password, "RIP_DIAGNOSTIC_FILE": str(diag)}

    result = subprocess.run(
        [
            rip_bin, "restic", "backup",
            "-r", str(restic_repo),
            "--added-size-limit", "1KB",
            str(fake_home),
        ],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert str(diag) in combined
    assert "ncdu --apparent-size -f" in combined
    # The big file should be called out as a significant contributor.
    assert "/big.bin" in combined
