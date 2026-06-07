from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path


_SERVICE_TEMPLATE = """\
[Unit]
Description=restic-in-peace backup orchestrator
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={rip} --config {config} backup
"""

_TIMER_TEMPLATE = """\
[Unit]
Description=Scheduled restic-in-peace backups

[Timer]
OnCalendar={schedule}
Persistent=true
RandomizedDelaySec=10m
Unit={name}.service

[Install]
WantedBy={wanted_by}
"""


def _resolve_rip() -> str:
    """Absolute path to the running rip executable. Baked into the unit so
    activations survive `PATH` changes (no-venv shells, sudo, etc.)."""
    return os.path.realpath(sys.argv[0])


def _resolve_config(config: str) -> str:
    return os.path.abspath(config)


def run(
    config: str,
    schedule: str = "hourly",
    unit_dir: str | None = None,
    name: str = "rip-backup",
    system: bool = False,
    enable: bool = False,
) -> int:
    """Render rip-backup.{service,timer} and write them. With `system=True`
    the units go to /etc/systemd/system/ (root timer, requires running rip via
    sudo); otherwise they go to ~/.config/systemd/user/."""
    rip_path = _resolve_rip()
    config_path = _resolve_config(config)

    if not Path(config_path).is_file():
        print(
            f"warning: config file {config_path} does not exist yet — "
            f"the timer will fail until you create it",
            file=sys.stderr,
        )

    if unit_dir is not None:
        target_dir = Path(unit_dir)
    elif system:
        target_dir = Path("/etc/systemd/system")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        config_home = Path(xdg) if xdg else Path.home() / ".config"
        target_dir = config_home / "systemd" / "user"

    target_dir.mkdir(parents=True, exist_ok=True)

    service_path = target_dir / f"{name}.service"
    timer_path = target_dir / f"{name}.timer"

    service_content = _SERVICE_TEMPLATE.format(rip=rip_path, config=config_path)
    timer_content = _TIMER_TEMPLATE.format(
        schedule=schedule,
        name=name,
        wanted_by="timers.target" if system else "default.target",
    )

    service_path.write_text(service_content)
    timer_path.write_text(timer_content)

    print(f"Wrote {service_path}")
    print(f"Wrote {timer_path}")

    scope = "system" if system else "user"
    flag = "" if system else "--user "
    next_steps = textwrap.dedent(f"""\

        Next steps:
          systemctl {flag}daemon-reload
          systemctl {flag}enable --now {name}.timer
          systemctl {flag}list-timers {name}.timer
    """)

    if not enable:
        print(next_steps)
        return 0

    import subprocess
    cmd_reload = ["systemctl"] + (["--user"] if not system else []) + ["daemon-reload"]
    cmd_enable = ["systemctl"] + (["--user"] if not system else []) + [
        "enable", "--now", f"{name}.timer",
    ]
    print(f"Running: {' '.join(cmd_reload)}")
    rc = subprocess.run(cmd_reload).returncode
    if rc != 0:
        return rc
    print(f"Running: {' '.join(cmd_enable)}")
    return subprocess.run(cmd_enable).returncode
