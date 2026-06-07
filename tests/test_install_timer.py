import os
import subprocess
from pathlib import Path


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
