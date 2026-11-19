"""Market today shows today's stories plus the last trading day's, never older ones."""
from datetime import datetime

import news

SGT = news.SGT


def at(y, m, d, h=9):
    return datetime(y, m, d, h, tzinfo=SGT)


def test_a_weekday_reaches_back_to_yesterday():
    assert str(news.window_start(at(2026, 11, 17))) == "2026-11-16"          # Tuesday -> Monday
    assert news.window_words(at(2026, 11, 17)) == "yesterday"


def test_a_monday_keeps_fridays_stories():
    assert str(news.window_start(at(2026, 11, 16))) == "2026-11-13"          # Monday -> Friday
    assert news.window_words(at(2026, 11, 16)) == "Friday"


def test_the_weekend_reaches_back_to_friday():
    assert str(news.window_start(at(2026, 11, 14))) == "2026-11-13"          # Saturday -> Friday
    assert str(news.window_start(at(2026, 11, 15))) == "2026-11-13"          # Sunday -> Friday


def test_older_stories_are_left_out(tmp_path):
    import db
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    for title, when in [("Old story on Sunday", "2026-11-15T20:00"), ("Monday story", "2026-11-16T08:00"),
                        ("Tuesday story", "2026-11-17T07:30")]:
        conn.execute("INSERT INTO news (title, url, source, published) VALUES (?, ?, ?, ?)",
                     (title, "https://www.straitstimes.com/" + title.replace(" ", "-"), "The Straits Times", when))
    got = [r["title"] for r in news.recent(conn, now=at(2026, 11, 17))]
    assert got == ["Tuesday story", "Monday story"]
