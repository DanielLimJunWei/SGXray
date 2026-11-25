"""The dividend calendar (s04): announced ex-dates checked daily, used in the forecast in place of a guess, and the
forecast shown month by month. No internet: Yahoo's calendar is faked."""

from datetime import date, datetime

import pandas as pd
import pytest

import db
import market
from income import calendar, forecast
from market import SGT, download_announced, update_announced

AS_OF = "2026-11-06"
EVENING = datetime(2026, 11, 6, 18, 0, tzinfo=SGT)


@pytest.fixture
def dbs(conn, user_id):
    """200 DBS. In the last year it went ex-dividend on 13 Nov, 8 Apr, 11 May and 14 Aug."""
    db.add_trade(conn, user_id, "D05.SI", "2025-01-02", "BUY", 200, 40.0, 0)
    db.save_prices(conn, "D05.SI", [("2025-01-02", 40.0), (AS_OF, 70.0)])
    db.save_dividends(conn, "D05.SI", [("2025-11-13", 0.75), ("2026-04-08", 0.81), ("2026-05-11", 0.81),
                                       ("2026-08-14", 0.81)])
    return user_id


# ---------- Checking Yahoo every evening ----------

class FakeTicker:
    def __init__(self, value):
        self.calendar = {"Ex-Dividend Date": value} if value is not None else {}


@pytest.mark.parametrize("value, want", [
    (date(2026, 11, 30), ["2026-11-30"]),                        # a date
    (datetime(2026, 11, 30, 0, 0), ["2026-11-30"]),              # a datetime
    ([date(2026, 11, 30), date(2027, 5, 4)], ["2026-11-30", "2027-05-04"]),
    ("2026-11-30", ["2026-11-30"]),
    (None, []),                                                  # an ETF: no calendar
    ("soon", []),                                                # nonsense is ignored, never saved
])
def test_yahoos_calendar_is_read_in_any_shape_it_comes(monkeypatch, value, want):
    monkeypatch.setattr(market.yf, "Ticker", lambda t: FakeTicker(value))
    assert download_announced("D05.SI") == want


def test_only_dates_still_to_come_are_kept_and_a_moved_date_replaces_the_old_one(conn):
    update_announced(conn, ["D05.SI"], now=EVENING, download=lambda t: ["2026-08-14", "2026-11-13"], pause=0)
    assert db.get_announced(conn, "D05.SI", "2026-11-06") == ["2026-11-13"]          # 14 Aug has passed
    update_announced(conn, ["D05.SI"], now=EVENING, download=lambda t: ["2026-11-17"], pause=0)
    assert db.get_announced(conn, "D05.SI", "2026-11-06") == ["2026-11-17"]          # moved: old one gone


def test_a_failed_check_keeps_what_was_known(conn):
    update_announced(conn, ["D05.SI"], now=EVENING, download=lambda t: ["2026-11-13"], pause=0)

    def offline(ticker):
        raise ConnectionError("no internet")

    [r] = update_announced(conn, ["D05.SI"], now=EVENING, download=offline, pause=0)
    assert "download failed" in r.error and r.dates == ["2026-11-13"]


# ---------- The forecast ----------

def test_without_announcements_every_date_is_an_estimate(conn, dbs):
    f = forecast(conn, dbs, AS_OF)
    assert list(f["status"]) == ["estimate"] * 4
    assert f.iloc[0]["expected"] == pd.Timestamp("2026-11-13")


def test_an_announced_date_replaces_the_guess_it_matches(conn, dbs):
    db.save_announced(conn, "D05.SI", ["2026-11-17"], "2026-11-06")       # last year 13 Nov: same payout
    f = forecast(conn, dbs, AS_OF)
    row = f.iloc[0]
    assert (row["expected"], row["status"], row["based_on"]) == (pd.Timestamp("2026-11-17"), "announced", "2025-11-13")
    assert row["total"] == pytest.approx(150.0)                            # amount: still last year's
    assert len(f) == 4 and list(f["status"]).count("announced") == 1


def test_a_new_dividend_is_listed_with_its_amount_unknown_not_guessed(conn, dbs):
    db.save_announced(conn, "D05.SI", ["2027-01-20"], "2026-11-06")       # nothing like it last year
    f = forecast(conn, dbs, AS_OF)
    new = f[f["expected"] == pd.Timestamp("2027-01-20")].iloc[0]
    assert new["status"] == "announced" and pd.isna(new["total"]) and pd.isna(new["based_on"])
    assert f["total"].sum() == pytest.approx(150 + 162 * 3)              # the unknown one isn't counted


def test_an_announcement_beyond_the_12_months_is_left_out(conn, dbs):
    db.save_announced(conn, "D05.SI", ["2027-12-01"], "2026-11-06")
    assert "announced" not in set(forecast(conn, dbs, AS_OF)["status"])


def test_one_announcement_takes_one_guess_only(conn, dbs):
    # 8 Apr and 11 May are both within 45 days of 20 Apr: only the nearest (8 Apr + 1 year) is replaced.
    db.save_announced(conn, "D05.SI", ["2027-04-20"], "2026-11-06")
    f = forecast(conn, dbs, AS_OF)
    assert list(f["status"]).count("announced") == 1
    assert pd.Timestamp("2027-05-11") in set(f["expected"])


# ---------- Month by month ----------

def test_the_calendar_lists_every_month_and_agrees_with_the_table(conn, dbs):
    db.save_announced(conn, "D05.SI", ["2026-11-17", "2027-01-20"], "2026-11-06")
    f = forecast(conn, dbs, AS_OF)
    months = calendar(f, AS_OF)
    assert [m["month"] for m in months][:3] == ["Nov 2026", "Dec 2026", "Jan 2027"] and len(months) == 13
    assert months[0]["part"] == "from the 7th" and months[-1]["part"] == "to the 6th"
    nov, jan = months[0], months[2]
    assert (nov["total"], nov["announced"], nov["unknown"]) == (pytest.approx(150.0), 1, 0)
    assert (jan["payouts"], jan["unknown"], jan["total"]) == (1, 1, 0.0)
    assert months[1]["payouts"] == 0                                          # December: "Nothing expected"
    assert sum(m["total"] for m in months) == pytest.approx(f["total"].sum())


@pytest.mark.parametrize("as_of, first, last", [
    ("2026-11-30", ("Dec 2026", None), ("Nov 2027", None)),                    # month end: 12 whole months
    ("2027-02-28", ("Mar 2027", None), ("Feb 2028", "to the 28th")),           # 2028 has a 29 Feb
    ("2026-11-01", ("Nov 2026", "from the 2nd"), ("Nov 2027", "to the 1st")),
])
def test_the_first_and_last_months_say_exactly_which_days_they_cover(as_of, first, last):
    months = calendar(pd.DataFrame(columns=forecast.__globals__["FORECAST_COLUMNS"]), as_of)
    assert (months[0]["month"], months[0]["part"]) == first
    assert (months[-1]["month"], months[-1]["part"]) == last



def test_the_dashboard_shows_the_calendar_and_marks_each_date(tmp_path, monkeypatch):
    """A real page: an announced date, an estimate and a new dividend, each saying what it is in words, every
    month listed, and nothing blank or "n/a"."""
    import re
    from test_trades import signed_up
    from app import create_app
    from instruments import seed_instruments
    path = tmp_path / "cal.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    a = create_app(path)
    a.config["MARKET_DOWNLOAD"] = lambda c, t: True
    client = signed_up(a, "cal@example.com")
    uid = db.get_user_by_email(conn, "cal@example.com")["id"]
    db.add_trade(conn, uid, "D05.SI", "2025-01-02", "BUY", 200, 40.0, 0)
    db.save_prices(conn, "D05.SI", [("2025-01-02", 40.0), (AS_OF, 70.0)])
    db.save_prices(conn, "ES3.SI", [("2025-01-02", 3.5), (AS_OF, 4.0)])
    db.save_dividends(conn, "D05.SI", [("2025-11-13", 0.75), ("2026-04-08", 0.81)])
    db.save_announced(conn, "D05.SI", ["2026-11-17", "2027-01-20"], AS_OF)
    conn.close()
    html = client.get("/portfolio").get_data(as_text=True)
    cal = html[html.index('class="div-cal"'):html.index("</ol>", html.index('class="div-cal"'))]
    assert cal.count("<li") == 13 and cal.count("Nothing expected") == 10
    assert "date announced" in cal and "Amount not announced yet" in cal and "$150.00" in cal
    table = html[html.index('id="forecast-title"'):]
    table = table[:table.index("</table>")]
    assert ">announced</button>" in table and ">estimate</button>" in table and "not announced yet" in table
    assert not re.search(r">\s*(n/a|nan|NaN|None)\s*<", table + cal)
