# How to backup your laptop

## Prerequisites

### restic-in-peace

```bash
pip install --upgrade setuptools wheel
python setup.py bdist_wheel
pip install dist/restic_in_peace*.whl
```

Make sure your PATH includes `/home/$USER/.local/bin`:

```
# Add a line like this ~/.profile
export PATH="$PATH:/home/$USER/.local/bin"
```

You should set it in `~/.profile` and not in your `{bash|zsh}rc`, since
`systemd-timer` will need it too.

### restic

It's packaged for most distros, just install it from there. This tool
has been tested with recent restic versions (0.16+), where `scan_finished`
is emitted under `verbose_status`.

## Configuration file

Copy the sample configuration:

```bash
mkdir -p ~/.config/restic-in-peace
cp rip.sample.yaml ~/.config/restic-in-peace/rip.yaml
```

Generate a strong password and put it in the `profiles.common.env.RESTIC_PASSWORD`
field of your `rip.yaml`. The configuration file is intended to be self-contained:
no external password file is referenced.

```bash
head -c 16 /dev/urandom | base64 | sed 's/=//g'
# paste the result into rip.yaml under profiles.common.env.RESTIC_PASSWORD
```

**Also save the password off of your machine and/or print it.** Lock down the
file so only you can read it:

```bash
chmod 600 ~/.config/restic-in-peace/rip.yaml
```

You can declare multiple profiles to backup different data with different
frequencies, retention policies, etc. The sample file has one profile that
inherits from `common`. Each profile should have a unique tag (i.e. the
name of the profile). This is needed by restic-in-peace to grab the correct
snapshots when computing the size increase from the previous backup.

The bare minimum modifications you need are specifying which data to back up
and the repo it should be backed up to. Your friendly sysadmin will give you
the backup repo URL, which you'll need to set in `profiles.common.repository`.
If you want to experiment, you can use your own repo with a local path like
`/mnt/backups` or a URL such as `sftp:host:path`. Restic supports many
backends, [find the whole list here](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html).

These are the main parameters for specifying which data to back up:

* `profiles.<profile>.backup.source`: string or list of directories to back up.
    * Use absolute paths
    * Using `/home/<username>` and excluding only unneeded paths is recommended.
      Risk to back up useless stuff rather than to lose something important.
* `profiles.<profile>.backup.exclude`: string or list of glob-like
  [patterns](https://golang.org/pkg/path/filepath/#Match) to exclude
* `profiles.<profile>.backup.iexclude`: same as exclude, case insensitive
* `profiles.<profile>.backup.exclude-if-present`: string or list of filenames
  that exclude a directory if it contains one of them (e.g. `.do_not_backup`)

The configuration syntax is largely a mirror of restic flags: any key under
a profile (or its `backup`/`unlock`/... sub-section) becomes the corresponding
`--key value` flag passed to restic. Read `man restic` for the full list.

### restic-in-peace parameters

These parameters are added by restic-in-peace:

* `added-size-limit`: abort the backup if the size of the files to be added
  to the backup is over this threshold
* `skip-on-battery`: abort the backup if on battery power
* `wifi-whitelist`: abort the backup if the computer is routed through a
  wifi network not matching one of the provided regexes
* `wifi-blacklist`: abort the backup if the computer is routed through a
  wifi network matching one of the provided regexes
* `desktop-notifications`: if true, the `backup` orchestrator fires
  `notify-send` notifications at run-start, run-finish, and on each
  per-profile failure

Read `restic-in-peace --help` for more details. Settings can be placed
under a command-specific subsection (e.g. `backup`, `check`) to scope them
to that command.

# Run the first backup

Initialize the repository with:
```
restic-in-peace --config rip.yaml --name <profile> restic init
```

If you configured a sensible size limit in your configuration the first
backup will likely abort due to the limit. A size limit of `0` overrides
the watchdog.

```
restic-in-peace \
    --config ~/.config/restic-in-peace/rip.yaml \
    --name <profile> \
    restic backup \
    --added-size-limit 0
```

Re-run the backup. This should take much less time:

```
restic-in-peace --config rip.yaml --name <profile> restic backup
```

# Automation with systemd-timer

The timer included in the repo starts every day:

```
ln -s $PWD/systemd/rip@.service ~/.config/systemd/user/
ln -s $PWD/systemd/rip-daily@.timer ~/.config/systemd/user/
systemctl --user enable rip-daily@<profile>.timer
```

Check that the unit runs correctly:

```
systemctl --user start rip-daily@<profile>.timer
journalctl --user --follow --unit rip@<profile>.service
```

In case of failure, the backup will be automatically retried in 30 minutes.
You can also check the history of backup success/failures as follows:

```
journalctl --user -u rip@<profile>.service
```

# Verify the backup

First check the backup consistency. This does not read data, unless the
`--read-data` flag is supplied. This check is also run after every backup,
it should **never** fail.

```
restic-in-peace --config rip.yaml --name <profile> restic check
```

You should mount the backup and inspect it to ensure your important stuff
is actually being backed up. Follow the instructions in `README.md`.
