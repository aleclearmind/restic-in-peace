import yaml


# Config keys that map to a different restic flag name.
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


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def children_of(config, parent):
    """Names of profiles that directly inherit from `parent`, sorted."""
    return sorted(
        name
        for name, settings in config.get("profiles", {}).items()
        if isinstance(settings, dict) and settings.get("inherit") == parent
    )


def resolve(config, name, command):
    """Return (settings, env) for `command` under profile `name`, applying inheritance."""
    profiles = config.get("profiles", {})
    if name not in profiles:
        raise KeyError(f"Profile {name!r} not found")

    chain = []
    seen = set()
    current = name
    while current:
        if current in seen:
            raise ValueError(f"Inheritance cycle involving {current!r}")
        seen.add(current)
        chain.append(profiles[current])
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

    env = merged.pop("env", {})
    return merged, env


def has_section(config, name, section):
    """True if profile `name` (or any ancestor) defines a non-empty `section`."""
    profiles = config.get("profiles", {})
    seen = set()
    current = name
    while current and current not in seen:
        seen.add(current)
        profile = profiles.get(current, {})
        if profile.get(section):
            return True
        current = profile.get("inherit")
    return False


# Keys rip understands but restic does not — filter these out when invoking
# restic directly (e.g. from the collect-non-backuped-files command).
RIP_ONLY = frozenset({
    "added-size-limit", "skip-on-battery", "wifi-whitelist", "wifi-blacklist",
    "monitor-url", "desktop-notifications", "tee-restic-logs", "loglevel",
})


def to_argv(settings, command, drop_keys=frozenset()):
    """Translate `settings` (from `resolve`) to flag args and positional args."""
    settings = {k: v for k, v in settings.items() if k not in drop_keys}
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
