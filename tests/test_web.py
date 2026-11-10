"""Web pages: each one loads, shows the right numbers, and never shows 'nan' or crashes.

Flask's test client opens pages without starting a real server or browser.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # so `import app` finds app.py

import db  # noqa: E402
from app import create_app  # noqa: E402
from importer import DEMO_EMAIL  # noqa: E402
from instruments import seed_instruments  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "web.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    return create_app(db_path).test_client()


def load_demo(db_path, with_prices=True):
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, DEMO_EMAIL, "!demo-no-login")
    db.add_trade(conn, uid, "D05.SI", "2025-01-06", "BUY", 100, 40.00, 10.0)
    db.add_trade(conn, uid, "ES3.SI", "2025-01-06", "BUY", 1000, 3.50, 10.0)
    if with_prices:
        db.save_prices(conn, "D05.SI", [("2025-01-06", 40.0), ("2025-06-30", 44.0)])
        db.save_prices(conn, "ES3.SI", [("2025-01-06", 3.5), ("2025-06-30", 3.8)])
    conn.close()


def test_home_page_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"See inside your portfolio." in r.data
    assert b"Start learning" in r.data                 # speaks to people with no stocks yet too
    assert b'href="/demo"' in r.data


def test_demo_without_data_explains_how_to_load_it(client):
    r = client.get("/demo")
    assert r.status_code == 200
    assert b"isn't loaded yet" in r.data


def test_demo_shows_holdings_and_totals(client, db_path):
    load_demo(db_path)
    html = client.get("/demo").get_data(as_text=True)
    assert "D05.SI" in html and "ES3.SI" in html
    # 100 x $44 + 1000 x $3.80 = $8,200 worth now; cost $4,010 + $3,510 = $7,520; profit $680.
    assert "$8,200.00" in html
    assert "+$680.00" in html
    assert "30 June 2025" in html                       # "prices as of"
    assert "What does this mean?" in html
    for section in ("stock by stock", "Dividend yields", "Dividends expected"):
        assert section in html
    assert "helped you" in html or "held you back" in html or "same as the market" in html
    assert "nan" not in html.lower().replace("financial", "").replace("finance", "")


def test_xray_chart_has_monthly_layers(client, db_path):
    load_demo(db_path)
    html = client.get("/demo").get_data(as_text=True)
    assert "Your portfolio, X-rayed" in html
    assert 'id="xray-data"' in html
    # Jan 2025 month end: $7,520 put in; the last day saved that month is the buy day, at cost price.
    assert '"money": 7520.0' in html or '"money":7520.0' in html
    assert "Show as a table" in html                    # the same numbers without the animation
    assert "Animation: on" in html                      # the switch to turn it off


def test_chart_data_layers_add_up(db_path):
    """Your money + price gains + dividends = worth + dividends, every month."""
    import app as web
    from history import value_history
    load_demo(db_path)
    conn = db.get_connection(db_path)
    user = db.get_user_by_email(conn, DEMO_EMAIL)
    h = value_history(conn, user["id"])
    rows = web._monthly_chart(h)
    conn.close()
    assert [r["label"] for r in rows] == ["Jan 25", "Jun 25"]
    last = rows[-1]
    assert round(last["money"] + last["gains"], 2) == 8200.00    # worth now
    assert last["divs"] == 0


def test_dividends_show_in_yields_and_forecast(client, db_path):
    load_demo(db_path)
    conn = db.get_connection(db_path)
    db.save_dividends(conn, "D05.SI", [("2025-04-10", 0.60)])
    conn.close()
    html = client.get("/demo").get_data(as_text=True)
    assert "$60.00" in html                            # 100 shares x $0.60, received and expected again
    assert "10 April 2026" in html                     # expected about a year after the last one


def test_missing_prices_show_na_not_nan(client, db_path):
    load_demo(db_path, with_prices=False)
    html = client.get("/demo").get_data(as_text=True)
    assert "No price yet" in html
    assert "n/a" in html
    assert "No STI ETF prices saved yet" in html
    assert "nan" not in html.lower().replace("financial", "").replace("finance", "")


def test_demo_is_read_only(client):
    assert client.post("/demo").status_code == 405     # 405 = "this page doesn't accept changes"


def test_safety_headers(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_design_preview_is_hidden_on_the_live_site(client):
    assert client.get("/design-system/preview.html").status_code == 404


def test_tap_a_term_every_word_has_a_meaning(client, db_path):
    """Every tappable word opens a popup that exists, and every popup has a meaning and an example."""
    import re
    import glossary
    load_demo(db_path)
    html = client.get("/demo").get_data(as_text=True)
    used = set(re.findall(r'popovertarget="term-([a-z-]+)"', html))
    assert {"dividend", "unrealised", "avg-cost", "yield", "sti-etf"} <= used   # ex-date only shows with a forecast
    for key in used:
        assert key in glossary.TERMS
        assert f'id="term-{key}"' in html
    for name, meaning, example in glossary.TERMS.values():
        assert name and meaning.endswith(".") and example
