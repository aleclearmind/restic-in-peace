from datetime import timedelta

import pytest

from restic_in_peace.utils.human_numbers import (
    format_duration,
    parse_duration,
)


@pytest.mark.parametrize("s, expected", [
    ("30s", timedelta(seconds=30)),
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
    ("2w", timedelta(weeks=2)),
])
def test_parse_duration_accepts(s: str, expected: timedelta) -> None:
    assert parse_duration(s) == expected


@pytest.mark.parametrize("s", [
    "",         # empty
    "24",       # missing suffix
    "1.5h",     # decimal not supported
    "1h2m",     # compound not supported
])
def test_parse_duration_rejects(s: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(s)


@pytest.mark.parametrize("td, expected", [
    (timedelta(seconds=90), "90s"),   # fractional minute falls back to seconds
    (timedelta(minutes=5), "5m"),
    (timedelta(hours=2), "2h"),
    (timedelta(days=1), "1d"),
    (timedelta(days=7), "1w"),
])
def test_format_duration(td: timedelta, expected: str) -> None:
    assert format_duration(td) == expected
