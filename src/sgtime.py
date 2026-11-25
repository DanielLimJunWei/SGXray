"""Singapore time, for every "today" in SGXray.

Python's date.today() is the SERVER's date. On your computer that's Singapore, but a hosting server usually
runs on UTC, 8 hours behind: from midnight to 8am in Singapore it would still be yesterday there, so a trade
made this morning would be refused as "in the future" (found in audit 4). Everything uses these instead.
Singapore has no daylight saving, so a fixed +8 hours is exact all year.
"""

from datetime import datetime, timedelta, timezone

SGT = timezone(timedelta(hours=8))


def now():
    """The time now in Singapore."""
    return datetime.now(SGT)


def today():
    """Today's date in Singapore."""
    return now().date()
