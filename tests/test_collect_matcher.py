"""Unit tests for collect._matches_exclude.

The function is a loose port of restic's exclude-pattern semantics; these
cases pin down the parts of restic's behavior we deliberately mimic and the
parts we deliberately don't.
"""

import pytest

from restic_in_peace.collect import _matches_exclude


# Single-segment, unanchored patterns are tested against each path component.
@pytest.mark.parametrize("path, pattern, expected", [
    # Basename match
    ("/home/me/foo.tmp", "*.tmp", True),
    ("/home/me/foo.txt", "*.tmp", False),
    # Ancestor-directory match (the part restic gets right and a naive glob
    # check would miss): excluding `node_modules` excludes everything under it.
    ("/home/me/proj/node_modules/x.js", "node_modules", True),
    ("/home/me/proj/lib/x.js", "node_modules", False),
    # The pre-fix regression: a literal "tmp" pattern fragment must not match
    # paths under /tmp/ unless `tmp` actually appears as a component.
    ("/tmp/whatever/foo.txt", "*.tmp", False),
    ("/tmp/whatever/foo.tmp", "*.tmp", True),
    # Character classes work via fnmatch.
    ("/var/log/syslog.1", "syslog.[0-9]", True),
    ("/var/log/syslog.x", "syslog.[0-9]", False),
])
def test_single_segment_unanchored(path: str, pattern: str, expected: bool) -> None:
    assert _matches_exclude(path, pattern) is expected


# Multi-segment unanchored patterns are tested against path suffixes.
@pytest.mark.parametrize("path, pattern, expected", [
    ("/home/me/proj/foo/bar.log", "foo/*.log", True),
    ("/home/me/proj/foo/bar.txt", "foo/*.log", False),
    # Suffix must be contiguous; bar.log alone won't satisfy foo/*.log.
    ("/home/me/proj/bar.log", "foo/*.log", False),
])
def test_multi_segment_unanchored(path: str, pattern: str, expected: bool) -> None:
    assert _matches_exclude(path, pattern) is expected


# Anchored patterns (leading /) are tested against the full absolute path.
# We deliberately don't try to model restic's "anchored-to-source-root"
# semantics; that's documented as a known limitation.
@pytest.mark.parametrize("path, pattern, expected", [
    ("/home/me/cache", "/home/me/cache", True),
    ("/home/me/cache/x", "/home/me/cache/*", True),
    ("/home/me/other", "/home/me/cache", False),
])
def test_anchored(path: str, pattern: str, expected: bool) -> None:
    assert _matches_exclude(path, pattern) is expected
