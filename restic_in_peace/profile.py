from __future__ import annotations

from typing import Any

import jsonschema
import yaml


# Config keys that map to a different restic flag name.
KEY_ALIASES: dict[str, str] = {
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


CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "profiles": {
            "type": "object",
            "additionalProperties": {"$ref": "#/$defs/profile"},
        },
        "fix-homes": {
            "type": "object",
            "additionalProperties": {"$ref": "#/$defs/fixHomeUser"},
        },
        "run-backup": {
            "type": "object",
            "additionalProperties": False,
            "required": ["log-path"],
            "properties": {
                "log-path": {"type": "string"},
            },
        },
    },
    "$defs": {
        "profile": {
            "type": "object",
            # restic flags and command sub-sections (backup, forget, ...) vary
            # too much to enumerate; only the rip-specific knobs are typed.
            "additionalProperties": True,
            "properties": {
                "inherit": {"type": "string"},
                "repository": {"type": "string"},
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": ["string", "number", "boolean"]},
                },
                "added-size-limit": {"type": ["string", "integer"]},
                "skip-on-battery": {"type": "boolean"},
                "wifi-whitelist": {"type": "array", "items": {"type": "string"}},
                "wifi-blacklist": {"type": "array", "items": {"type": "string"}},
                "monitor-url": {"type": "array", "items": {"type": "string"}},
                "desktop-notifications": {"type": "boolean"},
                "tee-restic-logs": {"type": "string"},
            },
        },
        "fixHomeUser": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
}

_validator = jsonschema.Draft202012Validator(CONFIG_SCHEMA)


class ConfigError(Exception):
    pass


def load_config(path: str) -> dict[str, Any]:
    try:
        with open(path) as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        raise ConfigError(f"Config file not found: {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"Could not parse {path} as YAML: {e}") from e

    try:
        _validator.validate(config)
    except jsonschema.ValidationError as e:
        location = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ConfigError(f"{path}: schema error at {location}: {e.message}") from e

    return config


def children_of(config: dict[str, Any], parent: str) -> list[str]:
    """Names of profiles that directly inherit from `parent`, sorted."""
    return sorted(
        name
        for name, settings in config.get("profiles", {}).items()
        if isinstance(settings, dict) and settings.get("inherit") == parent
    )


def resolve(config: dict[str, Any], name: str, command: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (settings, env) for `command` under profile `name`, applying inheritance."""
    profiles = config.get("profiles", {})
    if name not in profiles:
        raise KeyError(f"Profile {name!r} not found")

    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = name
    while current:
        if current in seen:
            raise ValueError(f"Inheritance cycle involving {current!r}")
        seen.add(current)
        chain.append(profiles[current])
        current = chain[-1].get("inherit")

    merged: dict[str, Any] = {}
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


def has_section(config: dict[str, Any], name: str, section: str) -> bool:
    """True if profile `name` (or any ancestor) defines a non-empty `section`."""
    profiles = config.get("profiles", {})
    seen: set[str] = set()
    current: str | None = name
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


def to_argv(
    settings: dict[str, Any],
    command: str,
    drop_keys: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Translate `settings` (from `resolve`) to flag args and positional args."""
    settings = {k: v for k, v in settings.items() if k not in drop_keys}
    sources = settings.pop("source", []) if command == "backup" else []
    if isinstance(sources, str):
        sources = [sources]

    flags: list[str] = []
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
