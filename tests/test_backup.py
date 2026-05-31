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
