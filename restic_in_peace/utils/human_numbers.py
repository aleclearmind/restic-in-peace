import math
import re
from datetime import timedelta


def capture_group(l, group_name=None):
    regexpr = "|".join(l)
    group_part = ""
    if group_name:
        group_part = f"?P<{group_name}>"
    return f"({group_part}{regexpr})"


number_capture_group = r"(?P<number>\d+(\.\d+)?)"
simple_number_regex = re.compile(number_capture_group)


si_magnitudes_short = {
    "": 0,
    "k": 3,
    "m": 6,
    "g": 9,
    "t": 12,
    "p": 15,
}
si_prefixes_short = {v: k for k, v in si_magnitudes_short.items()}
si_regex_short = re.compile(
    number_capture_group + r"( )*" + capture_group([k for k in si_magnitudes_short.keys() if k], group_name="prefix"),
    re.IGNORECASE,
)

si_magnitudes = {
    "": 0,
    "kilo": 3,
    "mega": 6,
    "giga": 9,
    "tera": 12,
    "peta": 15,
}
si_prefixes = {v: k for k, v in si_magnitudes.items()}
si_regex = re.compile(
    number_capture_group + r"( )*" + capture_group([k for k in si_magnitudes.keys() if k], group_name="prefix"),
    re.IGNORECASE,
)

bin_magnitudes = {
    "": 0,
    "kibi": 10,
    "mebi": 20,
    "gibi": 30,
    "tebi": 40,
    "pebi": 50,
}
bin_prefixes = {v: k for k, v in bin_magnitudes.items()}
bin_regex = re.compile(
    number_capture_group + r"( )*" + capture_group([k for k in bin_magnitudes.keys() if k], group_name="prefix"),
    re.IGNORECASE,
)

bin_magnitudes_short = {
    "": 0,
    "ki": 10,
    "mi": 20,
    "gi": 30,
    "ti": 40,
    "pi": 50,
}
bin_prefixes_short = {v: k for k, v in bin_magnitudes_short.items()}
bin_regex_short = re.compile(
    number_capture_group + r"( )*" + capture_group([k for k in bin_magnitudes_short.keys() if k], group_name="prefix"),
    re.IGNORECASE,
)


def to_si(n, unit="B", short=True):
    if n == 0:
        magnitude = 0
    else:
        magnitude = int(math.log10(n) - math.log10(n) % 3)
    n = n / (10 ** magnitude)
    if short:
        prefix = si_prefixes_short[magnitude].upper()
    else:
        prefix = si_prefixes[magnitude].upper()

    return "{:.2f}{}{}".format(n, prefix, unit)


def to_bin(n, unit="B", short=True):
    if n == 0:
        magnitude = 0
    else:
        magnitude = int(math.log2(n) - math.log2(n) % 10)
    n = n / (2 ** magnitude)
    if short:
        prefix = bin_prefixes_short[magnitude].upper()
    else:
        prefix = bin_prefixes[magnitude].upper()
    return "{:.2f}{}{}".format(n, prefix, unit)


def parse(s):
    m = si_regex.match(s)
    if m:
        n = float(m.group("number"))
        prefix = m.group("prefix").lower()
        return n * 10 ** si_magnitudes[prefix]

    m = bin_regex.match(s)
    if m:
        n = float(m.group("number"))
        prefix = m.group("prefix").lower()
        return n * 2 ** bin_magnitudes[prefix]

    m = bin_regex_short.match(s)
    if m:
        n = float(m.group("number"))
        prefix = m.group("prefix").lower()
        return n * 2 ** bin_magnitudes_short[prefix]

    m = si_regex_short.match(s)
    if m:
        n = float(m.group("number"))
        prefix = m.group("prefix").lower()
        return n * 10 ** si_magnitudes_short[prefix]

    m = simple_number_regex.match(s)
    if m:
        return float(m.group(1))

    raise ValueError(f"Could not parse {s} as number")


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_REGEX = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$")


def parse_duration(s: str) -> timedelta:
    """Parse strings like '24h', '7d', '30m' into a timedelta. Single integer +
    one of s/m/h/d/w; whitespace tolerated."""
    m = _DURATION_REGEX.match(s)
    if not m:
        raise ValueError(
            f"Could not parse {s!r} as duration; expected '<int><s|m|h|d|w>'"
        )
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n * _DURATION_UNITS[unit])


def format_duration(td: timedelta) -> str:
    """Render a timedelta as the largest whole-unit it fits in: 7200s → '2h',
    90s → '90s'. Used for short summary rows ('last 3h ago')."""
    seconds = int(td.total_seconds())
    if seconds < 0:
        return f"-{format_duration(-td)}"
    for unit, n in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= n and seconds % n == 0:
            return f"{seconds // n}{unit}"
    return f"{seconds}s"


if __name__ == "__main__":
    parse_testcases = [
        ("1B", 1),
        ("1000B", 1000),
        ("1KB", 10 ** 3),
        ("1MB", 10 ** 6),
        ("1GB", 10 ** 9),
        ("1TB", 10 ** 12),
        ("1PB", 10 ** 15),
        ("1kilo", 10 ** 3),
        ("1mega", 10 ** 6),
        ("1giga", 10 ** 9),
        ("1tera", 10 ** 12),
        ("1peta", 10 ** 15),
        ("1kibi", 2 ** 10),
        ("1mebi", 2 ** 20),
        ("1gibi", 2 ** 30),
        ("1tebi", 2 ** 40),
        ("1pebi", 2 ** 50),
        ("1ki", 2 ** 10),
        ("1mi", 2 ** 20),
        ("1gi", 2 ** 30),
        ("1ti", 2 ** 40),
        ("1pi", 2 ** 50),
    ]
    for testcase, expected in parse_testcases:
        assert parse(testcase) == expected
    print("Tests ok")
