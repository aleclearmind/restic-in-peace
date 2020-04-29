## How to backup your laptop

### Prerequisites

**resticprofile**
```bash
curl -LO https://raw.githubusercontent.com/creativeprojects/resticprofile/master/install.s
chmod +x install.sh
sudo ./install.sh -b /usr/local/bin
```

**notify-send**

It is packaged in most distros:

* Arch: `libnotify` 
* Other distros: TODO

**restic-in-peace.py**

```bash
TODO: package and writeup instructions
```

### Configuration file

Choose a strong password (e.g. `head -c 16 /dev/urandom | xxd -p`) and put it in `~/.config/backup/restic_password`. **Also save the password off of your machine and/or print it**.

Create a folder in your home which will hold your configuration file
```
mkdir ~/.config/backup
cp resticprofile.sample.json ~/.config/backup/resticprofile.json
``` 

In the example file there is only one profile which inherits some properties from the `common` profile.
You can create multiple profiles to backup different data with different frequencies, retention policies, etc.
Each profile should have at least one unique tag, this is needed by the wrapper to grab the correct 
snapshots when computing the size increase from the previous backup.
 
The bare minimum modifications you need are specifying which data to backup and the repo it should be backed up to.
Your friendly sysadmin will give you the backup repo URL, which you'll need to set in `common.repository`.

These are the main parameters for specifying which data to backup:

* `<profile>.backup.source`: string or list of directories to backup. 
    * Use absolute paths
    * Using `/home/<username>` and excluding only unneded paths is recommended. Risk to backup useless stuff rather than to lose something important.
* `<profile>.backup.exclude`: string or list of glob-like [patterns](https://golang.org/pkg/path/filepath/#Match) to exclude
* `<profile>.backup.iexclude`: same as exclude, case insensitive
* `<profile>.backup.exclude-if-present`: string or list of filenames that exclude a directory if it contains one of them (e.g. .do_not_backup, .git)

These parameters are added by the custom wrapper:

* `common.added-size-limit`: abort the backup if the size of the files to be added to the backup is over this threshold
* `common.skip-on-battery`: abort the backup if on battery power
* `common.wifi-whitelist`: abort the backup if the computer is routed through a wifi network not matching one of the provided regexes
* `common.wifi-blacklist`: abort the backup if the computer is routed through a wifi network matching one of the provided regexes

The configuration file syntax is quite self explanatory and largely reflects restic flags. 
Read `man restic` and the configuration syntax reference [here](https://github.com/creativeprojects/resticprofile/#configuration-file-reference).
Unrecognized flags will be passed to restic as-is.

## Run the first backup

Run the first backup with an increased size limit, otherwise the backup will likely abort due to the limit in the configuration.
```
resticprofile -c ~/.config/backup/resticprofile.json --name <profile> --added-size-limit 200000000000 backup
``` 

Re-run the backup. This should take much less time
```
resticprofile -c ~/.config/backup/resticprofile.json --name <profile> backup
```

## Automation with systemd-timer

The timer included in the repo starts every day systemd-timer:
```
cp resticprofile@.service ~/.config/systemd/user/
cp resticprofile-daily@.timer ~/.config/systemd/user/
systemctl --user enable resticprofile-daily@<profile>.timer
```

Check that the unit runs correctly:
```
systemctl --user start resticprofile-daily@<profile>.timer
journalctl --follow --unit resticprofile@<profile>.service
```

## Verify the backup

First check the backup consistency. This does not read data, unless the `--read-data` flag is supplied.
This check is also run after every backup, it should **never** fail.

```
resticprofile -c ~/.config/backup/resticprofile.json --name <profile> check
```

You should mount the backup and inspect it to ensure your important stuff is actually being backed up.
Follow the instructions in `README.md`.