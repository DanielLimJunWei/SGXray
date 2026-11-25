"""Limits on ordinary use (audit 4): page floods per person or network address, the open demo page, and saved
changes per person per hour. Logins, sign-ups and lookups keep their own limits (test_auth.py, test_lookup.py)."""

import ratelimit
from test_trades import add, app, db_path, downloads, signed_up, token  # noqa: F401  (fixtures)


def test_the_window_counts_per_key_and_forgets_old_events():
    w = ratelimit.Window(60)
    assert all(w.allow("a", 3, now=t) for t in (0, 1, 2))
    assert not w.allow("a", 3, now=3)                       # 4th in a minute: refused
    assert w.allow("b", 3, now=3)                           # someone else isn't affected
    assert w.allow("a", 3, now=61)                          # the first one has dropped out of the minute


def test_a_flood_of_pages_from_one_address_is_paused(app, monkeypatch):
    monkeypatch.setattr(ratelimit, "PAGES_PER_MINUTE", 5)
    c = app.test_client()
    codes = [c.get("/learn").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]
    other = app.test_client()
    assert other.get("/learn", environ_base={"REMOTE_ADDR": "10.9.9.9"}).status_code == 200


def test_the_open_demo_has_its_own_lower_limit_and_static_files_never_count(app, monkeypatch):
    monkeypatch.setattr(ratelimit, "DEMO_PER_MINUTE", 2)
    c = app.test_client()
    assert [c.get("/demo").status_code for _ in range(3)] == [200, 200, 429]
    assert c.get("/learn").status_code == 200              # other pages still open
    assert all(c.get("/static/css/site.css").status_code == 200 for _ in range(5))


def test_saved_changes_are_limited_per_person(app, monkeypatch):
    monkeypatch.setattr(ratelimit, "CHANGES_PER_HOUR", 3)
    c = signed_up(app)
    codes = [add(c, quantity=str(10 + i)).status_code for i in range(4)]
    assert codes == [302, 302, 302, 429]
    bob = signed_up(app, "bob@example.com")
    assert add(bob).status_code == 302                      # one person's limit isn't anyone else's
