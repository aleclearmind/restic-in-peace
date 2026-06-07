import subprocess

from .conftest import snapshot_count


def test_backup_via_profile_creates_snapshot(
    fake_home, restic_repo, restic_password, rip_bin, restic_bin, write_config, test_env
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
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "restic", "backup", "p1"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_profile_inheritance_overrides(
    fake_home, restic_repo, restic_password, rip_bin, restic_bin, write_config, test_env
):
    # `common` points at a bogus repo; `p1` overrides it with the real one.
    (fake_home / "doc.txt").write_text("hi\n")
    config = write_config({
        "profiles": {
            "common": {
                "repository": "/nonexistent/bogus",
                "env": {"RESTIC_PASSWORD": restic_password},
            },
            "p1": {
                "inherit": "common",
                "repository": str(restic_repo),
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "restic", "backup", "p1"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_forget_translates_policy_flags(
    fake_home, restic_repo, restic_password, rip_bin, restic_bin, write_config, test_env
):
    # Seed two snapshots so forget --keep-last 1 has something to remove.
    (fake_home / "doc.txt").write_text("v1\n")
    config = write_config({
        "profiles": {
            "p1": {
                "repository": str(restic_repo),
                "env": {"RESTIC_PASSWORD": restic_password},
                "backup": {"source": [str(fake_home)]},
                "forget": {"keep-last": 1},
            },
        },
    })

    for content in ("v1\n", "v2\n", "v3\n"):
        (fake_home / "doc.txt").write_text(content)
        subprocess.run(
            [rip_bin, "--config", str(config), "restic", "backup", "p1"],
            capture_output=True, text=True, env=test_env, check=True,
        )
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 3

    result = subprocess.run(
        [rip_bin, "--config", str(config), "restic", "forget", "p1"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_unknown_profile_fails(rip_bin, write_config, test_env):
    config = write_config({"profiles": {"p1": {"repository": "/x"}}})
    result = subprocess.run(
        [rip_bin, "--config", str(config), "restic", "snapshots", "missing"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0
    assert "missing" in (result.stdout + result.stderr)
