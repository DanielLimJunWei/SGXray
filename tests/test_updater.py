"""Automatic daily price updates (w410): when they run, that only one runs, and that pages can tell."""

from datetime import date, datetime, timedelta, timezone

import pytest

import db
import updater
from market import BENCHMARK
from test_trades import app, db_path, downloads, signed_up  # noqa: F401  (fixtures)

SGT = timezone(timedelta(hours=8))
FRI_4PM = datetime(2026, 11, 13, 16, 0, tzinfo=SGT)       # Friday, before the close is final
FRI_7PM = datetime(2026, 11, 13, 19, 0, tzinfo=SGT)
SAT = datetime(2026, 11, 14, 12, 0, tzinfo=SGT)
MON_10AM = datetime(2026, 11, 16, 10, 0, tzinfo=SGT)


@pytest.mark.parametrize("now, day", [(FRI_4PM, date(2026, 11, 12)), (FRI_7PM, date(2026, 11, 13)),
                                      (SAT, date(2026, 11, 13)), (MON_10AM, date(2026, 11, 13))])
def test_the_last_trading_day_skips_weekends_and_waits_for_the_close(now, day):
    assert updater.last_trading_day(now) == day


def conn_with_sti(db_path, latest):
    conn = db.get_connection(db_path)
    db.save_prices(conn, BENCHMARK, [(latest, 3.5)])
    return conn


def test_nothing_runs_when_the_prices_are_already_up_to_date(db_path):
    conn = conn_with_sti(db_path, "2026-11-13")
    assert updater.run_once(conn, FRI_7PM, update=lambda c: pytest.fail("shouldn't download")) == "not due"
    conn.close()


def test_a_new_close_is_downloaded_once_then_its_done(db_path):
    conn = conn_with_sti(db_path, "2026-11-12")
    calls = []

    def fake(c):
        calls.append(1)
        db.save_prices(c, BENCHMARK, [("2026-11-13", 3.6)])
        return True
    assert updater.run_once(conn, FRI_7PM, update=fake) == "updated"
    assert updater.run_once(conn, FRI_7PM, update=fake) == "not due"            # it has the close now
    assert calls == [1]
    assert updater.newest_saved(conn) == "2026-11-13"
    conn.close()


def test_if_yahoo_has_no_close_yet_it_tries_again_then_gives_up_for_the_day(db_path):
    conn = conn_with_sti(db_path, "2026-11-12")
    for _ in range(updater.MAX_TRIES):
        assert updater.run_once(conn, FRI_7PM, update=lambda c: True) == "no new close"
    assert updater.run_once(conn, FRI_7PM, update=lambda c: True) == "not due"   # a holiday: stop for today
    later = MON_10AM + timedelta(hours=9)                                        # Monday's close: a new day, new tries
    assert updater.due(conn, later)
    conn.close()


def test_only_one_update_runs_at_a_time(db_path):
    conn = conn_with_sti(db_path, "2026-11-12")
    assert updater._take_lock(conn, FRI_7PM)                                    # another process is running
    assert updater.run_once(conn, FRI_7PM, update=lambda c: pytest.fail("shouldn't run twice")) == "busy"
    stale = FRI_7PM + timedelta(minutes=updater.LOCK_MINUTES + 1)               # it crashed: the lock expires
    assert updater.run_once(conn, stale, update=lambda c: True) == "no new close"
    conn.close()


def test_a_crash_inside_the_download_never_stops_future_checks(db_path):
    conn = conn_with_sti(db_path, "2026-11-12")

    def boom(c):
        raise RuntimeError("Yahoo down")
    assert updater.run_once(conn, FRI_7PM, update=boom) == "failed"
    assert updater._take_lock(conn, FRI_7PM)                                     # the lock was let go
    conn.close()


def test_the_updater_never_starts_in_the_tests():
    assert updater.enabled() is False


def test_pages_can_ask_for_the_newest_close_without_logging_in(app, db_path):
    conn = conn_with_sti(db_path, "2026-11-13")
    conn.close()
    r = app.test_client().get("/prices/latest")
    assert r.status_code == 200 and r.get_json()["version"].startswith("2026-11-13/")
    assert r.headers["Cache-Control"] == "no-store"


def test_the_version_changes_when_any_stock_catches_up_not_only_the_newest_date(db_path):
    conn = conn_with_sti(db_path, "2026-11-13")
    db.save_prices(conn, "D05.SI", [("2026-11-12", 50.0)])
    before = updater.prices_version(conn)
    db.save_prices(conn, "D05.SI", [("2026-11-13", 51.0)])     # DBS catches up; the newest date stays the same
    assert updater.prices_version(conn) != before
    caught_up = updater.prices_version(conn)
    with conn:
        conn.execute("UPDATE prices SET close = 51.5 WHERE ticker = 'D05.SI' AND price_date = '2026-11-13'")
    assert updater.prices_version(conn) != caught_up              # a corrected close counts too
    conn.close()


def test_portfolio_pages_listen_for_new_prices_and_say_when_theyre_behind(app):
    c = signed_up(app)
    for path in ("/demo", "/portfolio", "/practice"):
        page = c.get(path).get_data(as_text=True)
        assert "data-live-prices=" in page and "js/live.js" in page, path
    from test_trades import add
    add(c)                                                       # the test prices are from January 2025
    page = c.get("/portfolio").get_data(as_text=True)
    assert "catching up: newer prices within about 15 minutes" in page          # the test prices are old
    assert "next update about 5:45pm" in page                                    # under Worth now
    assert 'data-roll="' in page                                 # the holdings' price and worth can roll


def test_the_daily_update_covers_every_held_stock_real_and_practice(db_path, monkeypatch):
    import market
    seen = {}
    for name in ("update_actions", "update_prices", "update_dividends"):
        monkeypatch.setattr(market, name, lambda conn, tickers, _n=name: seen.setdefault(_n, tickers) and [])
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, "zed@example.com", "x")
    db.add_trade(conn, uid, "D05.SI", "2025-01-02", "BUY", 1, 30.0)
    twin = db.practice_user(conn, uid)
    db.add_trade(conn, twin["id"], "ES3.SI", "2025-01-02", "BUY", 1, 30.0)
    assert updater.download_all(conn) is True
    assert seen["update_prices"] == ["D05.SI", "ES3.SI"]           # practice stocks get prices too
    conn.close()



@pytest.mark.parametrize("now, words", [
    (datetime(2026, 11, 12, 10, 0, tzinfo=SGT), "about 5:45pm today"),         # Thursday morning
    (datetime(2026, 11, 12, 19, 0, tzinfo=SGT), "about 5:45pm tomorrow"),      # Thursday evening
    (datetime(2026, 11, 13, 19, 0, tzinfo=SGT), "about 5:45pm on Monday"),     # Friday evening
    (datetime(2026, 11, 14, 9, 0, tzinfo=SGT), "about 5:45pm on Monday"),      # Saturday
])
def test_the_next_update_is_said_in_words(now, words):
    assert updater.next_update(now) == words
