import json


# Resticprofile config keys that map to a different restic flag name.
KEY_ALIASES = {
    "repository": "repo",
}

# Sub-sections of a profile that are command-specific: they override base
# settings only when that command is being invoked. Anything not in this set
# is treated as a top-level setting common to all commands.
COMMAND_SECTIONS = frozenset({
    "backup", "unlock", "snapshots", "restore", "mount",
    "check", "forget", "prune", "init", "find", "ls",
    "stats", "tag", "diff", "copy", "rebuild-index", "cat",
})

# Keys we recognize as resticprofile-only and silently drop. Forwarding them
# to restic would make restic reject the invocation.
RESTICPROFILE_ONLY = frozenset({
    "run-before", "run-after", "check-after", "retention",
    "lock-wait", "force-inactive-lock", "description",
    "ignore-on-battery", "ignore-on-battery-less-than",
})


def load_config(path):
    with open(path) as f:
        return json.load(f)


def resolve(config, name, command):
    """Return (settings, env) for `command` under profile `name`, applying inheritance."""
    if name not in config:
        raise KeyError(f"Profile {name!r} not found in config")

    chain = []
    seen = set()
    current = name
    while current:
        if current in seen:
            raise ValueError(f"Inheritance cycle involving {current!r}")
        seen.add(current)
        chain.append(config[current])
        current = chain[-1].get("inherit")

    merged = {}
    for profile in reversed(chain):
        for key, value in profile.items():
            if key == "inherit":
                continue
            if isinstance(value, dict) and key == "env":
                merged.setdefault("env", {}).update(value)
            elif isinstance(value, dict) and key in COMMAND_SECTIONS:
                merged.setdefault(key, {}).update(value)
            else:
                merged[key] = value

    command_settings = merged.pop(command, {})
    for section in COMMAND_SECTIONS:
        merged.pop(section, None)
    merged.update(command_settings)

    for key in RESTICPROFILE_ONLY:
        merged.pop(key, None)

    env = merged.pop("env", {})
    return merged, env


def to_argv(settings, command):
    """Translate `settings` (from `resolve`) to flag args and positional args."""
    settings = dict(settings)
    sources = settings.pop("source", []) if command == "backup" else []
    if isinstance(sources, str):
        sources = [sources]

    flags = []
    for key, value in settings.items():
        flag = "--" + KEY_ALIASES.get(key, key)
        if isinstance(value, bool):
            if value:
                flags.append(flag)
        elif isinstance(value, list):
            for item in value:
                flags.extend([flag, str(item)])
        else:
            flags.extend([flag, str(value)])

    return flags, [str(s) for s in sources]
