"""Tests for market.py. They use a fake download function, so no internet is needed."""

from datetime import date, datetime, timedelta

import db
from market import SGT, last_complete_day, update_prices

FRIDAY_EVENING = datetime(2026, 11, 6, 18, 0, tzinfo=SGT)
FRIDAY_AFTERNOON = datetime(2026, 11, 6, 15, 0, tzinfo=SGT)


class FakeDownload:
    """Pretends to be Yahoo: returns a close of 10.0 for every weekday asked for, and remembers the calls."""

    def __init__(self, fail_for=()):
        self.calls = []
        self.fail_for = fail_for

    def __call__(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        if ticker in self.fail_for:
            raise ConnectionError("no internet")
        rows, day = [], start
        while day <= end:
            if day.weekday() < 5:
                rows.append((day.isoformat(), 10.0))
            day += timedelta(days=1)
        return rows


def add_buy(conn, user_id, ticker, trade_date):
    db.add_trade(conn, user_id, ticker, trade_date, "BUY", 100, 10.0)


def test_close_is_only_final_after_530pm():
    assert last_complete_day(FRIDAY_EVENING) == date(2026, 11, 6)
    assert last_complete_day(FRIDAY_AFTERNOON) == date(2026, 11, 5)


def test_first_run_starts_at_first_trade(conn, user_id):
    add_buy(conn, user_id, "D05.SI", "2026-11-02")      # a Monday
    fake = FakeDownload()

    [result] = update_prices(conn, ["D05.SI"], now=FRIDAY_EVENING, download=fake, pause=0)

    assert fake.calls == [("D05.SI", date(2026, 11, 2), date(2026, 11, 6))]
    assert (result.added, result.latest, result.error) == (5, "2026-11-06", None)


def test_second_run_only_fetches_new_days(conn, user_id):
    add_buy(conn, user_id, "D05.SI", "2026-11-02")
    update_prices(conn, ["D05.SI"], now=FRIDAY_AFTERNOON, download=FakeDownload(), pause=0)   # saves up to Thu
    fake = FakeDownload()

    [result] = update_prices(conn, ["D05.SI"], now=FRIDAY_EVENING, download=fake, pause=0)

    assert fake.calls == [("D05.SI", date(2026, 11, 6), date(2026, 11, 6))]
    assert result.added == 1


def test_up_to_date_over_the_weekend_downloads_nothing(conn, user_id):
    add_buy(conn, user_id, "D05.SI", "2026-11-02")
    update_prices(conn, ["D05.SI"], now=FRIDAY_EVENING, download=FakeDownload(), pause=0)
    fake = FakeDownload()

    sunday = datetime(2026, 11, 8, 12, 0, tzinfo=SGT)
    [result] = update_prices(conn, ["D05.SI"], now=sunday, download=fake, pause=0)

    assert fake.calls == []
    assert result.added == 0


def test_benchmark_starts_at_first_trade_of_any_ticker(conn, user_id):
    add_buy(conn, user_id, "D05.SI", "2026-11-02")
    fake = FakeDownload()

    update_prices(conn, ["ES3.SI"], now=FRIDAY_EVENING, download=fake, pause=0)

    assert fake.calls[0][1] == date(2026, 11, 2)


def test_one_failure_does_not_stop_the_others(conn, user_id):
    add_buy(conn, user_id, "D05.SI", "2026-11-02")
    add_buy(conn, user_id, "O39.SI", "2026-11-02")

    results = update_prices(
        conn, ["D05.SI", "O39.SI"], now=FRIDAY_EVENING, download=FakeDownload(fail_for={"D05.SI"}), pause=0
    )

    assert "download failed" in results[0].error
    assert results[1].added == 5


def test_days_outside_the_range_are_ignored(conn, user_id):
    add_buy(conn, user_id, "D05.SI", "2026-11-02")

    def live_price_too(ticker, start, end):
        return [("2026-11-06", 10.0), ("2026-11-07", 99.0)]    # an extra day past the end

    [result] = update_prices(conn, ["D05.SI"], now=FRIDAY_EVENING, download=live_price_too, pause=0)

    assert result.latest == "2026-11-06"
