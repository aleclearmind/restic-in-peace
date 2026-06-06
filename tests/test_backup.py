import subprocess

from .conftest import snapshot_count


def test_backup_creates_snapshot(
    fake_home, restic_repo, restic_password, rip_bin, restic_bin, write_config, test_env
):
    # Direct CLI for `restic backup` no longer accepts a positional source —
    # the only way to give restic a source path is via a profile. So we drive
    # this through --config/--name now.
    (fake_home / "doc.txt").write_text("hello world\n")
    config = write_config({
        "profiles": {
            "p1": {
                "repository": str(restic_repo),
                "env": {"RESTIC_PASSWORD": restic_password},
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "--name", "p1", "restic", "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1
