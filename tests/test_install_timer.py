import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _systemd_unit_search_path() -> str | None:
    """Find a directory containing systemd's example/template user units
    (basic.target etc.) so `systemd-analyze verify --user` can resolve unit
    references. Returns None when nothing usable is on the host — the
    verify-based tests skip in that case rather than failing on hosts where
    systemd isn't installed."""
    analyze = shutil.which("systemd-analyze")
    if not analyze:
        return None
    candidates = [
        # nixpkgs systemd ships templated units under share/example/.
        Path(analyze).parent.parent / "example" / "systemd" / "user",
        # Standard FHS Linux installs.
        Path("/usr/lib/systemd/user"),
        Path("/lib/systemd/user"),
        Path("/run/current-system/sw/lib/systemd/user"),
    ]
    for c in candidates:
        if (c / "basic.target").exists():
            return str(c)
    return None


def _verify_units(unit_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run `systemd-analyze verify --user` over both unit files in unit_dir.
    Caller asserts the returncode."""
    search_path = _systemd_unit_search_path()
    if search_path is None:
        pytest.skip("systemd-analyze or systemd unit examples not available")
    runtime_dir = unit_dir.parent / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "XDG_RUNTIME_DIR": str(runtime_dir),
        "SYSTEMD_UNIT_PATH": f"{search_path}:{unit_dir}",
    }
    return subprocess.run(
        [
            "systemd-analyze", "verify", "--user",
            str(unit_dir / "rip-backup.service"),
            str(unit_dir / "rip-backup.timer"),
        ],
        capture_output=True, text=True, env=env,
    )


def test_writes_units_to_unit_dir(tmp_path, rip_bin, test_env):
    unit_dir = tmp_path / "units"
    config = tmp_path / "rip.yml"
    config.write_text("profiles: {}\n")

    result = subprocess.run(
        [
            rip_bin,
            "--config", str(config),
            "install-timer",
            "--unit-dir", str(unit_dir),
        ],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    service = unit_dir / "rip-backup.service"
    timer = unit_dir / "rip-backup.timer"
    assert service.exists() and timer.exists()

    service_content = service.read_text()
    # Absolute rip path baked in — survives PATH changes.
    expected_rip = os.path.realpath(rip_bin)
    assert f"ExecStart={expected_rip} --config {config} backup" in service_content
    assert "[Service]" in service_content

    timer_content = timer.read_text()
    assert "OnCalendar=hourly" in timer_content
    assert "Persistent=true" in timer_content
    assert "Unit=rip-backup.service" in timer_content


def test_custom_schedule_and_name(tmp_path, rip_bin, test_env):
    unit_dir = tmp_path / "units"
    config = tmp_path / "rip.yml"
    config.write_text("profiles: {}\n")

    result = subprocess.run(
        [
            rip_bin,
            "--config", str(config),
            "install-timer",
            "--unit-dir", str(unit_dir),
            "--name", "custom-rip",
            "--schedule", "*-*-* 03:00:00",
        ],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0

    assert (unit_dir / "custom-rip.service").exists()
    assert (unit_dir / "custom-rip.timer").exists()
    timer = (unit_dir / "custom-rip.timer").read_text()
    assert "OnCalendar=*-*-* 03:00:00" in timer
    assert "Unit=custom-rip.service" in timer


def test_user_install_uses_xdg_config_home(tmp_path, rip_bin, test_env):
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    config = tmp_path / "rip.yml"
    config.write_text("profiles: {}\n")

    env = {**test_env, "XDG_CONFIG_HOME": str(xdg)}
    result = subprocess.run(
        [rip_bin, "--config", str(config), "install-timer"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0
    assert (xdg / "systemd" / "user" / "rip-backup.service").exists()
    assert (xdg / "systemd" / "user" / "rip-backup.timer").exists()

    timer = (xdg / "systemd" / "user" / "rip-backup.timer").read_text()
    # User units want default.target, not timers.target.
    assert "WantedBy=default.target" in timer


def test_system_install_targets_timers_target(tmp_path, rip_bin, test_env):
    # We can't write to /etc in the test, but --unit-dir + --system gives us
    # the rendering path: WantedBy switches to timers.target.
    unit_dir = tmp_path / "units"
    config = tmp_path / "rip.yml"
    config.write_text("profiles: {}\n")

    result = subprocess.run(
        [
            rip_bin,
            "--config", str(config),
            "install-timer",
            "--system",
            "--unit-dir", str(unit_dir),
        ],
        capture_output=True, text=True, env=test_env,
    )
    assert result.returncode == 0

    timer = (unit_dir / "rip-backup.timer").read_text()
    assert "WantedBy=timers.target" in timer


def test_units_pass_systemd_analyze_verify(tmp_path, rip_bin, test_env):
    # Render the default-shape units and let systemd-analyze parse them.
    # Catches directive typos, malformed OnCalendar=, broken Unit= references.
    unit_dir = tmp_path / "units"
    config = tmp_path / "rip.yml"
    config.write_text("profiles: {}\n")

    subprocess.run(
        [
            rip_bin,
            "--config", str(config),
            "install-timer",
            "--unit-dir", str(unit_dir),
        ],
        capture_output=True, text=True, env=test_env, check=True,
    )

    result = _verify_units(unit_dir)
    assert result.returncode == 0, (
        f"systemd-analyze rejected the rendered units\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_verify_detects_bad_calendar_expression(tmp_path, rip_bin, test_env):
    # Sanity check: confirm the verify step is actually exercising the unit
    # files. If we feed it a nonsense OnCalendar= we should get a non-zero
    # exit. Without this test, a passing verify could silently mean nothing.
    unit_dir = tmp_path / "units"
    config = tmp_path / "rip.yml"
    config.write_text("profiles: {}\n")

    subprocess.run(
        [
            rip_bin,
            "--config", str(config),
            "install-timer",
            "--unit-dir", str(unit_dir),
            "--schedule", "this is not a calendar expression",
        ],
        capture_output=True, text=True, env=test_env, check=True,
    )

    result = _verify_units(unit_dir)
    assert result.returncode != 0, (
        "Expected systemd-analyze to reject a bogus OnCalendar value, "
        f"but it accepted it.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_warns_when_config_does_not_exist(tmp_path, rip_bin, test_env):
    unit_dir = tmp_path / "units"
    missing_config = tmp_path / "nonexistent.yml"

    result = subprocess.run(
        [
            rip_bin,
            "--config", str(missing_config),
            "install-timer",
            "--unit-dir", str(unit_dir),
        ],
        capture_output=True, text=True, env=test_env,
    )
    # The warning is informational; we still write the units (the user might
    # be writing rip.yml after laying the timer down).
    assert result.returncode == 0
    assert "does not exist" in result.stderr
    assert (unit_dir / "rip-backup.service").exists()
