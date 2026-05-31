import getpass
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


def _which(name, env_var):
    path = os.environ.get(env_var) or shutil.which(name)
    if not path:
        pytest.skip(f"{name!r} not on PATH and {env_var} not set")
    return path


@pytest.fixture(scope="session")
def restic_bin():
    return _which("restic", "RESTIC_BIN")


@pytest.fixture(scope="session")
def rip_bin():
    return _which("restic-in-peace", "RIP_BIN")


@pytest.fixture(scope="session")
def current_user():
    return os.environ.get("USER") or os.environ.get("LOGNAME") or getpass.getuser()


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture
def restic_password():
    return "test-password"


@pytest.fixture
def restic_repo(tmp_path, restic_bin, restic_password):
    repo = tmp_path / "repo"
    env = {**os.environ, "RESTIC_PASSWORD": restic_password}
    subprocess.run(
        [restic_bin, "init", "--repo", str(repo)],
        check=True,
        capture_output=True,
        env=env,
    )
    return repo


@pytest.fixture
def test_env(rip_bin, fake_home, current_user):
    """Subprocess env with HOME, USER, and PATH ready for invoking rip.

    Intentionally does NOT set RESTIC_PASSWORD; profile-driven tests rely on
    the profile's `env` block. Direct rip-backup tests should add it
    explicitly via test_env_with_password.
    """
    env = os.environ.copy()
    env.pop("RESTIC_PASSWORD", None)
    env["HOME"] = str(fake_home)
    env["USER"] = current_user
    env["PATH"] = os.path.dirname(rip_bin) + ":" + env.get("PATH", "")
    return env


@pytest.fixture
def test_env_with_password(test_env, restic_password):
    return {**test_env, "RESTIC_PASSWORD": restic_password}


@pytest.fixture
def write_config(tmp_path):
    def _write(config):
        path = tmp_path / "rip.yaml"
        path.write_text(yaml.safe_dump(config, default_flow_style=False))
        return path

    return _write


def snapshot_count(restic_bin, repo, password):
    env = {**os.environ, "RESTIC_PASSWORD": password}
    result = subprocess.run(
        [restic_bin, "snapshots", "-r", str(repo), "--json"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return len(json.loads(result.stdout))
