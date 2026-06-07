# restic-in-peace (`rip`)

`rip` is a wrapper around [restic](https://restic.net/) that turns a single `rip.yml` into the source of truth for "what to back up, where, with which retention policy, under which guard conditions". The same configuration drives a one-shot orchestrator (`rip backup`) and arbitrary ad-hoc restic invocations (`rip restic <subcommand> <profile>`).

## Features

- **Profile system.** Define repository, password, sources, exclude patterns, retention policy, and `rip`-specific knobs once in `rip.yml`, refer to them by name. Profiles inherit from a `common` ancestor.
- **Size-limit watchdog.** Aborts a profile when more data than `added-size-limit` is about to be written. Catches the "I committed an LLVM checkout into my home directory" mistake before it lands in the repo.
- **Battery and network gates.** Skip the run on battery power, on non-whitelisted networks, or on blacklisted networks.
- **Desktop notifications.** `notify-send` calls at run-start, run-end, and on every per-profile failure.
- **`fix-home`.** Enforce a stable dotfile layout (real files under `~/.dotfiles/`, symlinks at `~/.foo`) so the backup is reproducible across machines.
- **Pre-pass diagnostics.** Every backup writes an [ncdu](https://dev.yorhel.nl/ncdu/jsonfmt)-compatible JSON tree of what would be added — open it with `ncdu` to drill into "where did the bytes come from".

## Installation

### Nix flake (recommended)

```bash notest
nix profile install github:aleclearmind/restic-in-peace
```

For a one-off run without installing:

```bash notest
nix run github:aleclearmind/restic-in-peace -- --help
```

For development:

```bash notest
nix develop github:aleclearmind/restic-in-peace
```

### Manual: system `restic` + venv

You'll need a working `restic` (0.16+; tested against the version that emits `scan_finished` under `verbose_status`). Install it from your distro (`apt install restic`, `pacman -S restic`, ...) and then create a venv in your current directory and install `rip` straight from GitHub:

```bash notest
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install git+https://github.com/aleclearmind/restic-in-peace
```

`rip` is now on `$PATH` for as long as the venv is activated; future shells re-activate with `source venv/bin/activate`.

## The `rip.yml` file

`rip` reads its configuration from `./rip.yml` by default; override with `--config <path>`. The conventional location for a personal install is `~/.config/restic-in-peace/rip.yml`. The configuration is mostly a mirror of restic's flags: any key inside a profile becomes the corresponding `--key value` flag. `rip`-specific keys live at the top level.

The config file is intended to be self-contained — including the repository password under `profiles.common.env.RESTIC_PASSWORD` — so it needs to be locked down. Generate a strong password, write it into `rip.yml`, then tighten the permissions:

```bash
head -c 16 /dev/urandom | base64 | tr -d '='
```

```bash notest
chmod 600 ~/.config/restic-in-peace/rip.yml
```

**Save the password somewhere off the machine too** (a password manager, or printed and locked away). If the laptop dies and you only have the password inside the laptop's backup, you can't decrypt the backup.

### Anatomy

```yaml notest
# rip-wide knobs (orchestration, gates, notifications, log location)
added-size-limit: 5GB
skip-on-battery: true
wifi-whitelist:
  - home-wifi
wifi-blacklist:
  - hotel-network
desktop-notifications: true
log-path: backup-logs

# Profile definitions; each profile is a bag of restic settings + `env`.
# Profiles inherit from a parent via `inherit:`. The `common` profile is
# the conventional ancestor and is treated as a template: `rip backup`
# loops over every profile that inherits (directly or transitively) from
# `common`.
profiles:
  common:
    repository: /mnt/backups
    env:
      RESTIC_PASSWORD: secret
    forget:
      keep-daily: 7
      keep-weekly: 4
      keep-monthly: 6
      keep-yearly: 1
      prune: false

  laptop:
    inherit: common
    backup:
      source:
        - /home/me
      exclude:
        - "*.tmp"
      tag: laptop

# Dotfile-layout enforcement; one entry per user managed on this host.
fix-homes:
  me:
    ignore:
      - .cache
      - .config
    .dotfiles:
      - .vimrc
      - .bashrc
```

`profiles.<name>.<key>` becomes a top-level restic flag; `profiles.<name>.<command>.<key>` (under e.g. `backup:` or `forget:`) is scoped to that restic subcommand and overrides the profile defaults when that subcommand runs. `env:` is merged into the subprocess environment — that's how `RESTIC_PASSWORD` gets to restic. List-valued flags (`source`, `tag`, `exclude`, ...) expand to repeated `--key value` pairs.

A few keys are worth calling out:

- **`repository`** can be a local path, an SFTP URL, or any of the many backends restic supports — see [the restic backend list](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html). On a managed deployment your sysadmin will hand you the URL to set under `profiles.common.repository`.
- **`tag`** must be unique per profile. `rip` uses it to find the previous snapshot when computing the size-delta for `added-size-limit`; two profiles sharing a tag will compare against each other's snapshots and give nonsensical numbers.
- **`source`**, **`exclude`**, **`iexclude`** (case-insensitive exclude), and **`exclude-if-present`** (skip a directory containing one of the named marker files, e.g. `.do_not_backup` or `CACHEDIR.TAG`) are the four knobs that decide *what* gets backed up. Prefer naming a broad `source` (e.g. `/home/<user>`) and excluding the noise: when in doubt, err on backing up too much rather than missing something important.

### Top-level `rip` keys

| Key | Meaning |
| --- | --- |
| `added-size-limit` | Abort a profile when its dry-run pre-pass would add more than this many bytes (`5GB`, `500MB`, `0` to disable). |
| `skip-on-battery` | Refuse to run the orchestrator while on battery. |
| `wifi-whitelist` | List of regexes; the active wifi SSID must match one. |
| `wifi-blacklist` | List of regexes; abort if the active wifi SSID matches any. |
| `desktop-notifications` | Fire `notify-send` calls at run-start, run-end, fix-home abort, and per-profile failures. |
| `frequency` | Skip a profile when its newest snapshot is younger than this (`24h`, `7d`, `2w`, ...). State lives in the repo — `rip` queries `restic snapshots --tag <profile>` per run. Requires every profile to declare a `tag` matching its own name. |
| `log-path` | Absolute directory where each `rip backup` invocation creates a `YYYY-MM-DD-HH-MM-SS/` sub-directory with a `backup.log` and one `<profile>.ncdu.json` diagnostic per profile. |

### A minimal, runnable example

For the rest of this README we'll use a local restic repository under `$RIP_TMP` so every snippet is self-contained. The setup is a tiny home directory with one file and a `rip.yml` declaring a single `laptop` profile:

```bash
export RIP_TMP=$(mktemp -d)
mkdir -p $RIP_TMP/repo $RIP_TMP/data $RIP_TMP/logs
echo "important content" > $RIP_TMP/data/notes.txt
```

```bash
cat > $RIP_TMP/rip.yml <<EOF
log-path: $RIP_TMP/logs

profiles:
  common:
    repository: $RIP_TMP/repo
    env:
      RESTIC_PASSWORD: doctest-password

  laptop:
    inherit: common
    backup:
      source:
        - $RIP_TMP/data
      tag: laptop
EOF
```

Initialize the repository — same `restic init` you'd run by hand, but with the repo URL and password taken from the profile:

```bash
rip --config $RIP_TMP/rip.yml restic init laptop
```

## `rip backup`

`rip backup` is the orchestrator you'd schedule from a systemd timer. It:

1. runs `fix-home --strict` for every user in `fix-homes:`; if any reports pending actions, the whole run aborts before touching any repo;
2. iterates over every profile that inherits from `common`;
3. for each profile, runs a `restic backup --dry-run --verbose=2 --json` pre-pass to determine the size that would be added, writes a `<profile>.ncdu.json` diagnostic next to the log, and enforces `added-size-limit`;
4. if the limit is not exceeded, runs `restic unlock`, then `restic backup`, then (if a `forget:` section is present) `restic forget`, then `restic check`;
5. prints a `=== Summary ===` block with one row per profile.

The battery / wifi gates run once at the start and skip the whole invocation if they don't pass.

Run it:

```bash
rip --config $RIP_TMP/rip.yml backup
```

You should now have a snapshot in the repo. A second `rip backup` would be incremental and produce a second snapshot.

> **First-time gotcha.** On a freshly-initialized repository the pre-pass sees *every* file as new, which usually trips `added-size-limit` and the run aborts on the very first invocation. Either set `added-size-limit: 0` to disable the watchdog while you bootstrap, or run the first backup with `rip backup --ignore-added-size-limit`. Subsequent runs only see the delta from the previous snapshot and will fit under the limit.

The `restic check` at the end is run *after every backup* — it should never fail. If it does, something corrupted the repo (disk error, interrupted operation that left torn data); investigate before the next run.

### Useful flags

| Flag | Effect |
| --- | --- |
| `--dry-run` | Run the pre-pass only; skip `unlock`/`backup`/`forget`/`check`. The ncdu diagnostic still gets written. |
| `--only PROFILE` | Limit the run to specific profiles (repeatable). |
| `--log-path DIR` | Override `log-path:` for this invocation. |
| `--ignore-skip-on-battery` | Bypass the battery gate. |
| `--ignore-added-size-limit` | Bypass the size-limit gate for every profile. |
| `--ignore-wifi-whitelist` | Bypass the whitelist (the blacklist still applies). |
| `--ignore-frequency` | Bypass the per-profile frequency gate (run regardless of last-snapshot age). |

## `rip restic`: arbitrary restic commands with a profile

For anything beyond the daily orchestrated backup, use `rip restic <subcommand> <profile> [args...]`. The profile contributes `--repo`, `RESTIC_PASSWORD`, plus whatever's under the subcommand's section (e.g. `backup:` or `forget:`). Everything after the profile name is forwarded verbatim to restic.

List snapshots:

```bash
rip --config $RIP_TMP/rip.yml restic snapshots laptop
```

Run an integrity check:

```bash
rip --config $RIP_TMP/rip.yml restic check laptop
```

Remove a stale lock from an interrupted run:

```bash
rip --config $RIP_TMP/rip.yml restic unlock laptop
```

Take an ad-hoc snapshot outside the orchestrator:

```bash
rip --config $RIP_TMP/rip.yml restic backup laptop
```

Mount the repository as a read-only FUSE filesystem (for browsing or selective recovery — terminate the process with `^C` to unmount):

```bash notest
rip --config $RIP_TMP/rip.yml restic mount laptop /mnt/point
```

Restore files from a specific snapshot — `latest` works as a snapshot id:

```bash notest
rip --config $RIP_TMP/rip.yml restic restore laptop latest \
    --include $RIP_TMP/data/notes.txt \
    --target $RIP_TMP/restored \
    --verify
```

## `fix-home`

`fix-home` enforces a layout where the source of truth for every managed dotfile lives under `~/.dotfiles/` (or a sibling directory of your choosing) and the canonical location at `~/.foo` is a symlink into it. That way the backup of the dotfile is a regular file (not a symlink), and re-deploying it to a new machine is `ln -s ~/.dotfiles/.foo ~/.foo`.

The `fix-homes` section in `rip.yml` describes the expected layout per user:

```yaml notest
fix-homes:
  me:
    ignore:                # entries under ~ that are explicitly not managed
      - .cache
      - .config
    .dotfiles:             # destination directory under ~
      - .vimrc             # source: ~/.vimrc → ~/.dotfiles/.vimrc
      - .bashrc
```

Two modes:

- `rip fix-home` — emits a bash script that performs the renames / symlinking needed to bring the home into the declared layout. Review before piping to `bash`.
- `rip fix-home --strict` — exits non-zero if any action would be needed, prints nothing on stdout. This is what `rip backup` runs internally; a failure aborts the run before any restic command is invoked.

```bash notest
rip --config ~/.config/restic-in-peace/rip.yml fix-home | less
rip --config ~/.config/restic-in-peace/rip.yml fix-home | bash
```

The `--strict` gate inside `rip backup` is deliberate: if your home is in an inconsistent state, a backup taken now would either miss files or capture the wrong versions — better to refuse the run than to record garbage.

## Diagnosing "size-limit exceeded"

When a profile's pre-pass adds more bytes than `added-size-limit`, the orchestrator records a `size-limit exceeded` row in the summary, skips that profile entirely (no `restic backup` is ever spawned), and returns non-zero. There are four complementary ways to figure out what slipped in:

1. **Read the summary.** The `=== Summary ===` block prints each profile's would-add size next to its status, and under any size-limit row it includes an `ncdu --apparent-size -f <path>` invocation pointing at the diagnostic.
2. **Look at the ≥5% contributors.** Right above the summary, `rip` lists every path whose apparent size accounts for at least 5% of the data the pre-pass intended to add. A single large file shows up as itself; many small files in one directory aggregate up to the deepest directory that still passes the threshold. This is usually enough to identify what changed.
3. **Open the ncdu diagnostic.** Every profile, every run gets a `<profile>.ncdu.json` file under `log-path/<timestamp>/`. ncdu loads it directly — no live filesystem needed — and lets you walk the tree interactively:
   ```bash notest
   ncdu --apparent-size -f /var/log/rip/2026-06-07-09-12-44/laptop.ncdu.json
   ```
4. **Preview without committing.** `rip backup --dry-run` runs only the pre-pass, with the same diagnostic output but guaranteed not to write anything to the repo. Useful after touching the exclude list.

### Worked example

To see the failure path end-to-end, drop a new file into the source and configure an absurdly small `added-size-limit`:

```bash
echo "an LLVM checkout's worth of new bytes" > $RIP_TMP/data/oops.txt

cat > $RIP_TMP/tiny-limit.yml <<EOF
added-size-limit: 1B
log-path: $RIP_TMP/logs

profiles:
  common:
    repository: $RIP_TMP/repo
    env:
      RESTIC_PASSWORD: doctest-password

  laptop:
    inherit: common
    backup:
      source:
        - $RIP_TMP/data
      tag: laptop
EOF
```

The run aborts the `laptop` profile and exits non-zero (the `|| true` lets the rest of this README continue past the expected failure):

```bash
rip --config $RIP_TMP/tiny-limit.yml backup || true
```

The log explains *why* it aborted (the size limit) and points at the ncdu diagnostic that was written even though no `restic backup` ran:

```bash
grep -q "exceeds added-size-limit" $RIP_TMP/logs/*/backup.log
grep -q "size-limit exceeded" $RIP_TMP/logs/*/backup.log
test -n "$(find $RIP_TMP/logs -name 'laptop.ncdu.json' -print -quit)"
```

## Cleaning up

```bash
rm -rf $RIP_TMP
```

## Automating with systemd

The orchestration pattern is the same in both deployments: an hourly timer fires `rip backup`, the per-profile `frequency:` gate decides whether each profile actually runs, the `--system`/`User=root` variant handles a host-wide install. Pick the deployment that matches how you installed `rip`.

### User-level (venv install) — `rip install-timer`

For a venv install on a single user account:

```bash notest
rip --config ~/.config/restic-in-peace/rip.yml install-timer
```

That writes `rip-backup.service` and `rip-backup.timer` to `~/.config/systemd/user/` with the absolute path of the running `rip` binary and the absolute path you passed to `--config` baked in. Useful flags:

- `--schedule "*-*-* 03:00:00"` — override the default `hourly` `OnCalendar` expression.
- `--system` — write to `/etc/systemd/system/` instead, for a root timer (`sudo $(which rip) ... install-timer --system`).
- `--name custom-rip` — rename the unit pair if you want more than one timer (e.g. one for `laptop`, one for `media`).
- `--enable` — chain `systemctl daemon-reload` and `systemctl enable --now rip-backup.timer` after writing.

Without `--enable`, the command prints the next-step commands so you can review the units first.

### NixOS — declarative module

Import the NixOS module (no flake required — `fetchTarball` works fine):

```nix notest
{ pkgs, ... }: let
  rip-src = builtins.fetchTarball {
    url    = "https://github.com/aleclearmind/restic-in-peace/archive/master.tar.gz";
    sha256 = "0000000000000000000000000000000000000000000000000000";
  };
in {
  imports = [ "${rip-src}/nix/module.nix" ];

  services.restic-in-peace = {
    enable     = true;
    configFile = "/etc/restic-in-peace/rip.yml";
    schedule   = "hourly";
  };
}
```

Flake users wire it via `inputs.restic-in-peace.nixosModules.default` instead.

Notes:

- `configFile` is a string, not a Nix path. Passing a path would copy `rip.yml` (with its `RESTIC_PASSWORD`) into the world-readable Nix store. The module enforces an absolute path at evaluation time but doesn't touch the file itself — provision it out of band (manual `scp`, configuration management, etc.) and leave it mode `0600`.
- The generated service runs as `root`. `desktop-notifications: true` won't do anything useful from a root unit with no session bus; leave it `false` in this deployment.
- `services.restic-in-peace.package` defaults to a build from the source you imported; override it with an overlay-built rip if you need to.
