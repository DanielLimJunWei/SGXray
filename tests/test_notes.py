"""'Why I bought' notes on trades (w317): saved with the trade, shown again on the portfolio, safe as text."""

import sqlite3

import pytest

import db
from test_trades import GOOD, MONDAY, add, app, db_path, downloads, saved, signed_up, token  # noqa: F401  (fixtures)
from trades import NOTE_MAX, clean_note


def test_a_note_is_saved_and_shown_in_the_trades_list(app, db_path):
    c = signed_up(app)
    r = add(c, note="Steady bank dividends; holding for 5+ years")
    assert r.status_code == 302
    assert saved(db_path)[0]["note"] == "Steady bank dividends; holding for 5+ years"
    page = c.get("/trades").get_data(as_text=True)
    assert '<q class="trade-note">Steady bank dividends; holding for 5+ years</q>' in page


def test_no_note_is_saved_as_nothing_not_an_empty_string(app, db_path):
    c = signed_up(app)
    add(c, note="   ")
    assert saved(db_path)[0]["note"] is None
    assert "trade-note" not in c.get("/trades").get_data(as_text=True)


def test_the_note_can_be_changed_and_cleared(app, db_path):
    c = signed_up(app)
    add(c, note="First reason")
    tid = saved(db_path)[0]["id"]
    assert 'value="First reason"' in c.get(f"/trades/{tid}/edit").get_data(as_text=True)    # filled in
    base = {"csrf": token(c), "ticker": "D05.SI", "date": MONDAY, "side": "BUY", "quantity": "100", "price": "35.20"}
    c.post(f"/trades/{tid}/edit", data={**base, "note": "Better reason"})
    assert saved(db_path)[0]["note"] == "Better reason"
    c.post(f"/trades/{tid}/edit", data={**base, "note": ""})
    assert saved(db_path)[0]["note"] is None


def test_a_too_long_note_is_refused_and_kept_in_the_form(app, db_path):
    c = signed_up(app)
    r = add(c, note="x" * (NOTE_MAX + 1))
    assert r.status_code == 422
    assert "longer than 280 characters" in r.get_data(as_text=True)
    assert saved(db_path) == []
    assert add(c, note="x" * NOTE_MAX).status_code == 302                    # exactly the limit is fine


def test_a_note_is_shown_as_text_never_as_html(app):
    c = signed_up(app)
    add(c, note='<script>alert(1)</script> "hi"')
    for path in ("/trades", "/portfolio"):
        page = c.get(path).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_line_breaks_and_control_characters_become_spaces():
    assert clean_note("Good\r\nbank\t\x00 dividends ") == "Good bank dividends"


def test_the_database_refuses_an_over_long_note_too(db_path):
    """The form checks the length, and the table's CHECK rule backs it up."""
    conn = db.get_connection(db_path)
    uid = db.create_user(conn, "zed@example.com", "x")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_trade(conn, uid, "D05.SI", MONDAY, "BUY", 1, 30.0, note="x" * (NOTE_MAX + 1))
    conn.close()


def test_an_old_database_gets_the_note_column(tmp_path):
    """A database made before w317 has no note column: starting the app adds it, keeping the trades."""
    path = tmp_path / "old.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    conn.execute("ALTER TABLE trades DROP COLUMN note")
    assert "note" not in {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
    db.init_db(conn)
    assert "note" in {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
    conn.close()


def test_the_portfolio_shows_your_reason_beside_the_stock(app):
    c = signed_up(app)
    add(c, note="Steady bank dividends")
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'popovertarget="why-D05-SI-notes">Why you bought</button>' in page
    assert 'id="why-D05-SI-notes"' in page and "Steady bank dividends" in page
    assert "Does your reason still hold?" in page and "$30.00." in page        # today's price, from the saved close


def test_no_notes_means_no_link(app):
    c = signed_up(app)
    add(c)
    assert "Why you bought" not in c.get("/portfolio").get_data(as_text=True)


def test_a_sale_note_shows_as_your_notes(app):
    c = signed_up(app)
    add(c, note="Steady bank dividends")
    add(c, side="SELL", quantity="40", date="2025-06-02", note="Took some profit")
    page = c.get("/portfolio").get_data(as_text=True)
    assert ">Your notes</button>" in page and "Took some profit" in page and "sold 40 at" in page


def test_someone_elses_notes_are_never_shown(app):
    ann = signed_up(app)
    add(ann, note="Ann's private reason")
    bob = signed_up(app, "bob@example.com")
    add(bob)
    for path in ("/trades", "/portfolio"):
        assert "Ann&#39;s private reason" not in bob.get(path).get_data(as_text=True)


def test_a_stock_sold_completely_keeps_its_notes_in_the_sold_table(app):
    """Sold every share: the notes move with the stock to the Sold table, and the box asks how it turned out."""
    c = signed_up(app)
    add(c, note="Steady bank dividends")
    add(c, side="SELL", quantity="100", date="2025-06-02", note="Bank dividends were cut")
    page = c.get("/portfolio").get_data(as_text=True)
    sold = page[page.index('class="as-table sold"'):]
    assert 'popovertarget="why-D05-SI-notes">Your notes</button>' in sold      # the link sits in the Sold table
    assert "Did it turn out the way your note expected?" in page
    assert "Does your reason still hold?" not in page
