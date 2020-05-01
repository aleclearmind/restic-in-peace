import math

short_units = {
    0: "B",
    10: "KB",
    20: "MB",
    30: "GB",
    40: "TB",
    50: "PB",
}

units = {
    0: "B",
    10: "KB",
    20: "MB",
    30: "GB",
    40: "TB",
    50: "PB",
}


def to_si_units(n, short=True):
    if n == 0:
        magnitude = 0
    else:
        magnitude = int(math.log2(n) - math.log2(n) % 10)
    n = n / (2 ** magnitude)
    if short:
        unit = short_units[magnitude]
    else:
        unit = units[magnitude]

    return "{:.2f}{}".format(n, unit)
