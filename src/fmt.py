"""How SGXray shows numbers to people. One place, so every screen agrees.

- Money: -$200.00, never $-200.00.
- Unknown values (NaN, e.g. a missing price) show as "n/a", never "nan".
- Percentages: +12.34% / -5.00%.
The web app will use these too.
"""


def safe_console():
    """Stops printing from crashing on characters the Windows terminal can't show.

    Error messages repeat what the user typed. A CSV with Chinese characters (or digits from
    another script) crashed the importer while PRINTING its own error (audit 3). Now such
    characters show as '?' instead.
    """
    import sys
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass                                   # not a normal terminal (e.g. inside tests): nothing to do


def missing(x):
    """True for None and NaN (NaN is the only value that isn't equal to itself)."""
    return x is None or x != x


def cents(x):
    """Money rounded to the cent the way people and brokers do it: half a cent goes up (2.675 -> 2.68).

    Python's round() and "%.2f" work on the binary number, which for 2.675 is 2.67499999..., so they give 2.67.
    Going through the shortest decimal form ('2.675') rounds the number as it was typed or calculated."""
    from decimal import ROUND_HALF_UP, Decimal
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money(x, signed=False):
    """$1,234.56 / -$1,234.56 / n/a. signed=True also puts + on positives (for changes).
    Rounded to the cent first, so a tiny -0.004 shows as $0.00, not -$0.00."""
    if missing(x):
        return "n/a"
    x = cents(x)
    sign = "-" if x < 0 else ("+" if signed and x > 0 else "")
    return f"{sign}${abs(x):,.2f}"


def pct(x, signed=True):
    """+12.34% / -5.00% / n/a."""
    if missing(x):
        return "n/a"
    return f"{x:+.2%}" if signed else f"{x:.2%}"


def num(x, spec=",.2f"):
    """A plain number with a format, or n/a."""
    return "n/a" if missing(x) else format(x, spec)
