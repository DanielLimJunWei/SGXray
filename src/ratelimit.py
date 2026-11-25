"""Limits on ordinary use (audit 4, from "scope rate limits to the right level").

Logins, sign-ups, password tries, reset emails and stock lookups already have their own limits (auth.py). These
cover everything else, so a script can't flood the server:
- PAGES: page views per minute, per logged-in person (their id), or per network address when logged out (there's
  no identity to go on yet). Far above what a person reading can do. The open demo page, the heaviest one
  anyone can load without an account, has a lower limit.
- CHANGES: saved changes per hour per person (trades, plans, notes, practice trades). Kept in the database, so the
  limit holds across server processes; generous enough for typing in a whole history from contract notes.

The page counts are kept in memory, per server process: they reset when it restarts, which is fine for stopping a
flood, and costs no database write per page view.
"""

import threading
import time
from collections import deque

PAGES_PER_MINUTE = 120
DEMO_PER_MINUTE = 60          # logged out only: the demo page does the most work of any open page
CHANGES_PER_HOUR = 300
MAX_KEYS = 50_000             # forget the oldest visitors past this, so memory stays small


class Window:
    """Counts events per key over the last `seconds`. Thread-safe; old events fall out as time passes."""

    def __init__(self, seconds=60):
        self.seconds, self.hits, self.lock = seconds, {}, threading.Lock()

    def allow(self, key, limit, now=None):
        """Counts this event and says whether it's within `limit` for the window. A refused event isn't counted,
        so someone who's paused gets going again as soon as their older events fall out of the window."""
        now = time.monotonic() if now is None else now
        with self.lock:
            q = self.hits.get(key)
            if q is None:
                if len(self.hits) >= MAX_KEYS:
                    self.hits.pop(next(iter(self.hits)))           # the oldest key: dicts keep insertion order
                q = self.hits[key] = deque()
            while q and q[0] <= now - self.seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True
