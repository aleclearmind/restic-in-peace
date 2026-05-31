# restic-in-peace

rev.ng tool of choice for backup is [restic](https://restic.net/).
`restic-in-peace` (`rip`) is a wrapper around `restic` that adds:

* a profile system: define repositories, passwords, sources, and rip-specific
  options once in a YAML file and refer to them by name
* a watchdog that aborts the backup if a suspiciously large amount of data
  is about to be written (e.g. you forgot to exclude a new LLVM checkout)
* skipping the backup on non-whitelisted / blacklisted networks
* skipping the backup on battery power
* desktop notifications
* sending events to a monitor via HTTP

Read `configure_laptop.md` for instructions on how to install it and set up
your laptop.

## Profile-driven invocations

Most operations are done by invoking rip with `--config <file> --name <profile>`:

```
restic-in-peace --config rip.yaml --name <profile> <restic-command> [args...]
```

`<restic-command>` is any restic command (`backup`, `snapshots`, `restore`,
`mount`, `unlock`, `check`, ...). The profile contributes flags such as
`--repo`, `--password-file`, `--tag`, and rip's own `--added-size-limit`,
`--skip-on-battery`, etc. Anything passed on the CLI overrides the profile
value (or accumulates, for list flags like `--tag`).

## Restoring files and performing other operations

If you need just a couple of files or you want to explore multiple backups
to search for the point in time where a file was not damaged, mount a
read-only copy of the backup using FUSE. You will find all the snapshots,
organized by timestamp, tag, id and hostname.

```
restic-in-peace --config rip.yaml --name <profile> mount /mount/point
```

Note: to unmount the backup just terminate restic (CTRL+C). Before
unmounting make sure no process is holding open file descriptors against
the mount, or restic will not be able to properly unmount and you'll end
up with a stale FUSE mount. This is annoying, but does **not** endanger
the backed up data in any way.

If you want to restore files directly, first find the snapshot that
contains them:

```
restic-in-peace --config rip.yaml --name <profile> snapshots
```

You can also use the special snapshot id `latest`.

Use the `restore` command to extract some files:

```
restic-in-peace --config rip.yaml --name <profile> \
    restore <snapshot_id> \
    --include <path> --include <otherpath> \
    --target <target_dir> \
    --verify
```

## Disaster recovery

TODO: write this up when we've determined which offsite storage will be used

## My backup is failing!

Your repo might have a stale lock. Ensure no restic process is running,
then remove the lock with:

```
restic-in-peace --config rip.yaml --name <profile> unlock
```

If this does not help, append `--loglevel DEBUG` or `--loglevel TRACE` to
see more output.
