from datetime import timedelta

import pytest

from restic_in_peace.utils.human_numbers import (
    format_duration,
    parse_duration,
)


@pytest.mark.parametrize("s, expected", [
    ("30s", timedelta(seconds=30)),
    ("5m", timedelta(minutes=5)),
    ("1h", timedelta(hours=1)),
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
    ("2w", timedelta(weeks=2)),
    ("  3h  ", timedelta(hours=3)),
    ("12 h", timedelta(hours=12)),
])
def test_parse_duration_accepts(s: str, expected: timedelta) -> None:
    assert parse_duration(s) == expected


@pytest.mark.parametrize("s", [
    "", "h", "24", "24x", "1.5h", "1h2m", "-1h", "infinity",
])
def test_parse_duration_rejects(s: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(s)


@pytest.mark.parametrize("td, expected", [
    (timedelta(seconds=30), "30s"),
    (timedelta(seconds=90), "90s"),       # not a whole minute
    (timedelta(minutes=5), "5m"),
    (timedelta(hours=2), "2h"),
    (timedelta(days=1), "1d"),
    (timedelta(days=7), "1w"),
    (timedelta(days=14), "2w"),
    (timedelta(seconds=0), "0s"),
])
def test_format_duration(td: timedelta, expected: str) -> None:
    assert format_duration(td) == expected
