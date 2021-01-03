# How to backup your laptop

## Prerequisites

### restic-in-peace

```bash
pip3 install --user --upgrade setuptools wheel
python3 setup.py bdist_wheel
pip3 install --user dist/restic_in_peace*.whl
```

Make sure your PATH includes `/home/$USER/.local/bin`:

```
# Add a line like this ~/.profile
export PATH="$PATH:/home/$USER/.local/bin"
```

You should set it in `~/.profile` and not in your `{bash|zsh}rc`, since `systemd-timer` will need it too.

### resticprofile

```bash
curl -LO https://raw.githubusercontent.com/creativeprojects/resticprofile/master/install.sh
chmod +x install.sh
./install.sh -b ~/.local/bin
```

### restic

It's packaged for most distros, just install it from there.
This tool has been tested with restic 0.9.6, it should work with anything more recent and also with older versions,
as the features used by restic-in-peace have been implemented for a while.

## Configuration file

Choose a strong password:

```bash
mkdir -p ~/.config/restic-in-peace
head -c 16 /dev/urandom | base64 | sed 's/=//g' > ~/.config/restic-in-peace/restic_password
```

**Also save the password off of your machine and/or print it**.

Create a folder in your home which will hold your configuration file

```
cp resticprofile.sample.json ~/.config/restic-in-peace/resticprofile.json
```

You can create multiple profiles to backup different data with different frequencies, retention policies, etc.
In the example file there is only one profile which inherits some properties from the `common` profile.
Each profile should have a unique tag (i.e. the name of the profile). This is needed by restic-in-peace to grab the 
correct snapshots when computing the size increase from the previous backup.

The bare minimum modifications you need are specifying which data to backup and the repo it should be backed up to.
Your friendly sysadmin will give you the backup repo URL, which you'll need to set in `common.repository`.
If you want to experiment, you can use your own repo with local path like `/mnt/backups` or a URL such as `sftp:host:path`.
Restic supports many backends, [find the whole list here](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html).

You'll also need to update `global.restic-binary` to wherever you install `restic-in-peace`
(there seems to be a bug where the binary is not found even if it is in the path).

These are the main parameters for specifying which data to backup:

* `<profile>.backup.source`: string or list of directories to backup.
    * Use absolute paths
    * Using `/home/<username>` and excluding only unneded paths is recommended. Risk to backup useless stuff rather than to lose something important.
* `<profile>.backup.exclude`: string or list of glob-like [patterns](https://golang.org/pkg/path/filepath/#Match) to exclude
* `<profile>.backup.iexclude`: same as exclude, case insensitive
* `<profile>.backup.exclude-if-present`: string or list of filenames that exclude a directory if it contains one of them (e.g. .do_not_backup, .git)

The configuration file syntax is quite self explanatory and largely reflects restic flags.
Read `man restic` and the [configuration syntax reference](https://github.com/creativeprojects/resticprofile/#configuration-file-reference).
Unrecognized flags will be passed to restic as-is.

### restic-in-peace parameters

These parameters are added by restic-in-peace:

* `common.added-size-limit`: abort the backup if the size of the files to be added to the backup is over this threshold
* `common.skip-on-battery`: abort the backup if on battery power
* `common.wifi-whitelist`: abort the backup if the computer is routed through a wifi network not matching one of the provided regexes
* `common.wifi-blacklist`: abort the backup if the computer is routed through a wifi network matching one of the provided regexes
* `common.monitor-url`: list of URLs that receive a POST with backup events
* `common.desktop-notifications`: if true, use notify-send to notify of backup events
* `common.tee-restic-logs`: useful to redirect restic output to a file.

Read `restic-in-peace --help` for more details. Most options can be moved in more specific sections, i.e. if you want to receive desktop notifications only for backup commands you can move the setting to `common.backup`.

# Run the first backup

Initialize the repository with:
```
resticprofile -c resticprofile.json --name <profile> init
```

If you configured a sensible size limit in your configuration the first backup will likely abort due to the limit in the configuration. A size limit of 0 overrides the watchdog.

```
resticprofile \
    -c .config/restic-in-peace/resticprofile.json \
     --name <profile> \
     backup \
     --added-size-limit 0
```

Re-run the backup. This should take much less time

```
resticprofile -c resticprofile.json --name <profile> backup
```

# Automation with systemd-timer

The timer included in the repo starts every day systemd-timer:

```
ln -s $PWD/systemd/resticprofile@.service ~/.config/systemd/user/
ln -s $PWD/systemd/resticprofile-daily@.timer ~/.config/systemd/user/
systemctl --user enable resticprofile-daily@<profile>.timer
```

Check that the unit runs correctly:

```
systemctl --user start resticprofile-daily@<profile>.timer
journalctl --user --follow --unit resticprofile@<profile>.service
```

In case of failure, the backup will be automatically retried in 30 minutes.

# Verify the backup

First check the backup consistency. This does not read data, unless the `--read-data` flag is supplied.
This check is also run after every backup, it should **never** fail.

```
resticprofile -c resticprofile.json --name <profile> check
```

You should mount the backup and inspect it to ensure your important stuff is actually being backed up.
Follow the instructions in `README.md`.
