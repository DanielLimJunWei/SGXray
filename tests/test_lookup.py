"""Adding any SGX stock by its code, looked up on Yahoo (w309).

Yahoo is faked with the answers it really gave on 11 Nov 2026, so the tests never use the internet.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import lookup  # noqa: E402
from app import create_app  # noqa: E402
from instruments import seed_instruments  # noqa: E402

GOOD = "correct horse battery staple"
NOT_FOUND = {"quoteType": None, "exchange": None, "longName": None, "shortName": None}
YAHOO = {
    "C6L.SI": {"quoteType": "EQUITY", "exchange": "SES", "longName": "Singapore Airlines Limited",
               "shortName": "SIA", "sector": "Industrials", "industry": "Airlines"},
    "A17U.SI": {"quoteType": "EQUITY", "exchange": "SES", "longName": "CapitaLand Ascendas REIT",
                "sector": "Real Estate", "industry": "REIT - Industrial"},
    "G3B.SI": {"quoteType": "ETF", "exchange": "SES", "longName": "Nikko AM Singapore STI ETF"},
    "AAPL.SI": NOT_FOUND,
}


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "lookup.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    seed_instruments(conn)
    conn.close()
    return path


@pytest.fixture
def asked():
    return []


@pytest.fixture
def app(db_path, asked, monkeypatch):
    monkeypatch.setenv("SGXRAY_SECRET_KEY", "test-only-secret")
    a = create_app(db_path)

    def fake_yahoo(ticker):
        asked.append(ticker)
        return YAHOO.get(ticker, NOT_FOUND)
    a.config["TICKER_LOOKUP"] = fake_yahoo
    a.config["MARKET_DOWNLOAD"] = lambda conn, tickers: True
    return a


def token(client, path="/trades"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def signed_up(app, email="ann@example.com"):
    c = app.test_client()
    c.post("/signup", data={"csrf": token(c, "/signup"), "email": email, "password": GOOD, "password2": GOOD})
    return c


def look_up(client, code):
    return client.post("/trades/lookup", data={"csrf": token(client), "code": code})


def listed(db_path):
    conn = db.get_connection(db_path)
    rows = {r["ticker"]: dict(r) for r in db.get_instruments(conn)}
    conn.close()
    return rows


# ---------- The code people type ----------

@pytest.mark.parametrize("typed, ticker", [
    ("C6L", "C6L.SI"), ("c6l", "C6L.SI"), ("  C6L.si ", "C6L.SI"), ("5E2", "5E2.SI"), ("C38U.SI", "C38U.SI"),
])
def test_codes_are_tidied(typed, ticker):
    assert lookup.normalise(typed) == ticker


@pytest.mark.parametrize("typed", [
    "", "   ", "SINGAPORE AIRLINES", "C6L.SI.SI", "C6L.US", "https://evil.example/x", "../etc", "C6L;DROP",
    "C6L\nX", "C6L\n.SI", "TOOLONG1", "C 6L",
])
def test_anything_else_is_refused_before_yahoo_is_asked(app, asked, typed):
    assert lookup.normalise(typed) is None
    r = look_up(signed_up(app), typed)
    assert r.status_code == 422 and asked == []


# ---------- What Yahoo says ----------

def test_a_stock_a_reit_and_an_etf_are_each_recognised():
    assert lookup.describe(YAHOO["C6L.SI"]) == ("Singapore Airlines Limited", "stock", "Industrials")
    assert lookup.describe(YAHOO["A17U.SI"]) == ("CapitaLand Ascendas REIT", "reit", "REIT - Industrial")
    assert lookup.describe(YAHOO["G3B.SI"])[1] == "etf"


def test_things_sgxray_cant_track_are_refused():
    assert lookup.describe(NOT_FOUND) is None
    assert lookup.describe({}) is None
    assert lookup.describe({"quoteType": "EQUITY", "exchange": "NMS", "longName": "Apple Inc."}) is None   # not SGX
    assert lookup.describe({"quoteType": "INDEX", "exchange": "SES", "longName": "STI"}) is None
    assert lookup.describe({"quoteType": "EQUITY", "exchange": "SES"}) is None                          # no name


def test_a_very_long_name_from_yahoo_is_cut():
    name = lookup.describe({"quoteType": "EQUITY", "exchange": "SES", "longName": "A" * 5000})[0]
    assert len(name) == lookup.MAX_NAME_LENGTH


# ---------- On the website ----------

def test_a_new_stock_is_added_and_picked(app, db_path, asked):
    c = signed_up(app)
    r = look_up(c, "c6l")
    assert r.status_code == 302 and asked == ["C6L.SI"]
    assert listed(db_path)["C6L.SI"]["name"] == "Singapore Airlines Limited"
    page = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "is in the list now" in page
    assert '<option value="C6L.SI" selected>' in page


def test_then_a_trade_in_it_can_be_saved(app, db_path):
    c = signed_up(app)
    look_up(c, "A17U")
    r = c.post("/trades", data={"csrf": token(c), "ticker": "A17U.SI", "date": "2025-03-03", "side": "BUY",
                               "quantity": "1000", "price": "2.70"})
    assert r.status_code == 302
    assert listed(db_path)["A17U.SI"]["type"] == "reit"


def test_a_stock_already_listed_doesnt_ask_yahoo(app, asked):
    r = look_up(signed_up(app), "D05")
    assert r.status_code == 302 and asked == []


def test_a_code_yahoo_doesnt_know_is_explained(app, db_path):
    r = look_up(signed_up(app), "AAPL")
    assert r.status_code == 422 and "couldn't find AAPL.SI on SGX" in r.get_data(as_text=True).replace("&#39;", "'")
    assert "AAPL.SI" not in listed(db_path)


def test_yahoo_being_down_says_so(app):
    app.config["TICKER_LOOKUP"] = lambda ticker: None
    r = look_up(signed_up(app), "C6L")
    assert r.status_code == 503 and "couldn't be reached" in r.get_data(as_text=True).replace("&#39;", "'")


def test_lookups_are_rate_limited(app, asked):
    c = signed_up(app)
    for i in range(lookup.LOOKUPS_PER_HOUR):
        look_up(c, f"X{i}")
    r = look_up(c, "C6L")
    assert r.status_code == 429 and len(asked) == lookup.LOOKUPS_PER_HOUR


def test_you_must_be_logged_in(app, asked):
    c = app.test_client()
    r = c.post("/trades/lookup", data={"csrf": token(c, "/login"), "code": "C6L"})
    assert r.status_code == 302 and "/login" in r.headers["Location"] and asked == []


def test_the_form_needs_its_token(app, asked):
    c = signed_up(app)
    assert c.post("/trades/lookup", data={"code": "C6L"}).status_code == 400 and asked == []


def test_a_made_up_added_value_in_the_address_shows_nothing(app):
    page = signed_up(app).get("/trades?added=<script>").get_data(as_text=True)
    assert "is in the list now" not in page and "<script>" not in page


def test_lookups_are_logged(app, db_path):
    look_up(signed_up(app), "C6L")
    conn = db.get_connection(db_path)
    events = [r["event"] for r in conn.execute("SELECT event FROM security_log")]
    conn.close()
    assert "ticker_added" in events
