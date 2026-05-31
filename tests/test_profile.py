import subprocess

import yaml

from .conftest import snapshot_count


def _write_yaml(path, config):
    path.write_text(yaml.safe_dump(config, default_flow_style=False))
    return path


def test_backup_via_profile_creates_snapshot(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, test_env
):
    (fake_home / "doc.txt").write_text("hello\n")
    config = _write_yaml(tmp_path / "rip.yaml", {
        "profiles": {
            "common": {
                "repository": str(restic_repo),
                "password-file": str(restic_password),
            },
            "p1": {
                "inherit": "common",
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "--name", "p1", "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_profile_inheritance_overrides(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, test_env
):
    # `common` points at a bogus repo; `p1` overrides it with the real one.
    (fake_home / "doc.txt").write_text("hi\n")
    config = _write_yaml(tmp_path / "rip.yaml", {
        "profiles": {
            "common": {
                "repository": "/nonexistent/bogus",
                "password-file": str(restic_password),
            },
            "p1": {
                "inherit": "common",
                "repository": str(restic_repo),
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "--name", "p1", "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_inline_env_password(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, test_env
):
    (fake_home / "doc.txt").write_text("env-password\n")
    config = _write_yaml(tmp_path / "rip.yaml", {
        "profiles": {
            "p1": {
                "repository": str(restic_repo),
                "env": {"RESTIC_PASSWORD": restic_password.read_text().strip()},
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "--name", "p1", "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 1


def test_profile_size_limit_aborts(
    fake_home, restic_repo, restic_password, tmp_path, rip_bin, restic_bin, test_env
):
    (fake_home / "big.bin").write_bytes(b"x" * 10_000)
    config = _write_yaml(tmp_path / "rip.yaml", {
        "profiles": {
            "p1": {
                "repository": str(restic_repo),
                "password-file": str(restic_password),
                "added-size-limit": "1KB",
                "backup": {"source": [str(fake_home)]},
            },
        },
    })

    result = subprocess.run(
        [rip_bin, "--config", str(config), "--name", "p1", "backup"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0
    assert snapshot_count(restic_bin, restic_repo, restic_password) == 0


def test_unknown_profile_fails(
    tmp_path, rip_bin, test_env
):
    config = _write_yaml(tmp_path / "rip.yaml", {"profiles": {"p1": {"repository": "/x"}}})
    result = subprocess.run(
        [rip_bin, "--config", str(config), "--name", "missing", "snapshots"],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode != 0
    assert "missing" in result.stderr
