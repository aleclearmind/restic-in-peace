# Restic-in-peace

rev.ng tool of choice for backup is [restic](https://restic.net/).
We use [resticprofile](https://github.com/creativeprojects/resticprofile/) to manage multiple backup profiles
and a custom wrapper caller `restic-in-peace` to:

* detect if a suspiciously big amount of data is being backed up (i.e. you forgot to exclude a new LLVM repo), and in that case abort and alert the user.
* skip the backup on non-whitelisted/blacklisted networks
* skip the backup on battery power
* send desktop notifications
* send events to a monitor via HTTP

Read `configure_laptop.md` for instructions on how to install it and setup your laptop.

## Restoring files and performing other operations

If you need just a couple of files or you want to explore multiple backups to search for the point in time where a file was not damaged
you can mount a read-only copy of the backup using FUSE. You will find all the snapshots, organized by timestamp, tag, id and hostname.

```
resticprofile -c resticprofile.json --name <profile> mount /mount/point
```

Sometimes the virtual filesystem is not properly unmounted. Calling the `mount` command again will unmount it.

If you want to restore files directly, you first need to find the snapshot that contains them

```
resticprofile -c resticprofile.json --name <profile> snapshots
```

You can also use the special snapshot id `latest`.

Use the `restore` command to extract some files

```
resticprofile -c resticprofile.json                     \
    --name <profile> restore <snapshot_id>              \
    --include <path> --include <otherpath>              \
    --target <target_dir>                               \
    --verify
```

### Other commands

You can call `resticprofile` with any restic and restic-in-peace option like this

```
resticprofile -c resticprofile.json --name <profile> [command] [--option, ...]
```

The restic options must come after the command! Refer to `man restic` for all commands and options.

## Disaster recovery

TODO: write this up when we've determined which offsite storag will be used

## My backup is failing!

This is probably due to a stale lock, for example due to connectivity loss. Ensure no restic process is running, then remove the lock using

```
resticprofile -c resticprofile.json --name <profile> unlock
```

If this does not work, run with `--loglevel DEBUG` or `--loglevel TRACE` at the end of the command to see more output.
