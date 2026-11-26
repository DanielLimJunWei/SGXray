"""REIT health (s17): the REIT's own figures with their date and source, payouts a unit from saved distributions,
warnings at MAS's lines, and a reason in words wherever a number is missing."""

import re
from datetime import date

import pytest

import db
import reits
from reits import Figures
from test_trades import app, db_path, downloads, signed_up, token  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 26)
URL = "https://example.com/results.pdf"
MINE = [
    Figures("C38U.SI", "2025-12-31", 38.6, 3.7, "2026-08-12", "CICT 1H 2026", URL),
    Figures("C38U.SI", "2026-06-30", 37.4, 3.9, "2026-08-12", "CICT 1H 2026", URL),
    Figures("A17U.SI", "2026-03-31", 46.0, 1.7, "2026-05-01", "Made-up REIT", URL),       # near the limit, low cover
]


@pytest.fixture
def holder(conn, user_id):
    days = ["2024-11-01", "2025-11-03", "2026-11-20"]
    for t in ["C38U.SI", "A17U.SI", "M44U.SI", "D05.SI"]:
        db.save_prices(conn, t, [(d, 2.0) for d in days])
        db.add_trade(conn, user_id, t, "2024-11-01", "BUY", 1000, 2.0)
    db.save_dividends(conn, "C38U.SI", [("2025-02-12", 0.05), ("2025-08-12", 0.05),       # the year before: 10 cents
                                        ("2026-02-13", 0.05), ("2026-08-19", 0.06)])      # the last 12 months: 11 cents
    db.save_dividends(conn, "A17U.SI", [("2025-08-01", 0.08), ("2026-08-01", 0.06)])      # down 25%
    return user_id


def test_health_by_hand(conn, holder):
    rows = {r["ticker"]: r for r in reits.health(conn, holder, TODAY, MINE)}
    assert set(rows) == {"C38U.SI", "A17U.SI", "M44U.SI"}                 # REITs only: DBS is a bank
    c = rows["C38U.SI"]
    assert (c["figures"].leverage, c["before"].leverage) == (37.4, 38.6)
    assert c["leverage_room"] == pytest.approx(12.6) and c["flags"] == []
    assert c["age_days"] == 149 and not c["stale"]                         # 30 Jun -> 26 Nov 2026
    assert c["dpu_12m"] == pytest.approx(0.11) and c["dpu_prior"] == pytest.approx(0.10)
    assert c["dpu_change"] == pytest.approx(0.10)
    a = rows["A17U.SI"]
    assert a["flags"] == ["near-limit", "icr-low"] and a["dpu_change"] == pytest.approx(-0.25)
    assert a["age_days"] == 240 and a["stale"]                             # older than 200 days: newer are likely out
    m = rows["M44U.SI"]
    assert m["figures"] is None and m["dpu_12m"] == 0 and m["dpu_change"] is None


def test_the_explanation_warns_at_mas_lines(conn, holder):
    ex = reits.explain(reits.health(conn, holder, TODAY, MINE))
    watch = " ".join(ex.watch_out)
    assert "within 4.0 points of MAS's 50% limit" in watch
    assert "below 1.8 times" in watch and "25% less a unit" in watch
    assert "CapitaLand Integrated" not in watch                          # nothing to watch there
    below = [Figures("A17U.SI", "2026-06-30", 30.0, 1.4, "2026-08-01", "x", URL)]
    assert "below MAS's minimum" in " ".join(reits.explain(reits.health(conn, holder, TODAY, below)).watch_out)


def test_no_reits_no_section(conn, user_id):
    db.save_prices(conn, "D05.SI", [("2026-11-20", 40.0)])
    db.add_trade(conn, user_id, "D05.SI", "2026-11-20", "BUY", 10, 40.0)
    assert reits.health(conn, user_id, TODAY) == []


def test_which_reits_are_due():
    rows = {t: (latest, age, is_due) for t, latest, age, is_due in reits.due(TODAY, ["M44U.SI"], MINE)}
    assert rows["C38U.SI"][2] is False and rows["A17U.SI"][2] is True and rows["M44U.SI"] == (None, None, True)


def test_every_entered_figure_is_sane_and_sourced(conn):
    known = {r["ticker"]: r["type"] for r in db.get_instruments(conn)}
    for f in reits.FIGURES:
        assert known.get(f.ticker) == "reit", f
        assert 0 < f.leverage <= 60 and 0 < f.icr < 50, f
        assert date.fromisoformat(f.period_end) < date.fromisoformat(f.announced), f
        assert f.url.startswith("https://") and f.source, f
    assert len({(f.ticker, f.period_end) for f in reits.FIGURES}) == len(reits.FIGURES)   # no period twice


# ---------- The page ----------

def test_your_reit_shows_with_its_source_and_no_blanks(app):
    c = signed_up(app)
    c.post("/trades", data={"csrf": token(c), "ticker": "C38U.SI", "date": "2025-01-02", "side": "BUY",
                            "quantity": "100", "price": "2", "fees": ""})
    html = c.get("/portfolio").get_data(as_text=True)
    assert 'id="reits-title">REIT health' in html
    section = html[html.index('id="reits-title"'):html.index('id="risk-title"')]
    assert "37.4%" in section and "3.9 times" in section
    assert 'from <a href="https://www.capitaland.com/' in section and 'rel="noopener noreferrer"' in section
    assert not re.search(r">\s*(n/a|nan|NaN|None)\s*<", section)


def test_a_note_from_the_reit_shows_on_its_card(app):
    c = signed_up(app)
    c.post("/trades", data={"csrf": token(c), "ticker": "M44U.SI", "date": "2025-01-02", "side": "BUY",
                            "quantity": "100", "price": "1.2", "fees": ""})
    html = c.get("/portfolio").get_data(as_text=True)
    assert "37.5%" in html and "Its own figure without that is 40.4%." in html


def test_a_reit_without_figures_says_why(conn, holder):
    """No REIT SGXray knows is missing figures today, so this uses a list with CICT's left out."""
    [row] = [r for r in reits.health(conn, holder, TODAY, MINE[2:]) if r["ticker"] == "C38U.SI"]
    assert row["figures"] is None and row["dpu_12m"] == pytest.approx(0.11)
