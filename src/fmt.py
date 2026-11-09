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


def money(x, signed=False):
    """$1,234.56 / -$1,234.56 / n/a. signed=True also puts + on positives (for changes)."""
    if missing(x):
        return "n/a"
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
