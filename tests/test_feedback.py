"""Feedback (s06): anyone can send a note; it's only saved (never shown to anyone else), limited per hour, and only
ever records a page on this site as where it came from."""

import db
import feedback
from test_trades import app, db_path, downloads, signed_up, token  # noqa: F401  (fixtures)


def rows(db_path):
    conn = db.get_connection(db_path)
    out = [dict(r) for r in db.get_feedback(conn)]
    conn.close()
    return out


def test_every_page_links_to_it_with_where_you_came_from(app):
    html = app.test_client().get("/learn").get_data(as_text=True)
    assert 'href="/feedback?from=/learn">Feedback</a>' in html


def test_a_visitor_can_send_a_note_with_an_optional_email(app, db_path):
    c = app.test_client()
    r = c.post("/feedback", data={"csrf": token(c, "/feedback"), "message": "  The X-ray chart confused me \r\n",
                                  "reply_to": "me@example.com", "page": "/learn/fees"})
    assert r.status_code == 302 and "sent=1" in r.headers["Location"]
    assert "your note was sent" in c.get(r.headers["Location"]).get_data(as_text=True)
    [f] = rows(db_path)
    assert (f["message"], f["reply_to"], f["page"], f["account"]) == (
        "The X-ray chart confused me", "me@example.com", "/learn/fees", None)


def test_logged_in_it_is_saved_with_your_account_and_in_your_data(app, db_path):
    c = signed_up(app)
    c.post("/feedback", data={"csrf": token(c, "/feedback"), "message": "Love it", "reply_to": "ignored@example.com"})
    [f] = rows(db_path)
    assert f["account"] == "ann@example.com" and f["reply_to"] is None       # your account is the reply address
    assert [x["message"] for x in c.get("/account/data").get_json()["feedback"]] == ["Love it"]
    conn = db.get_connection(db_path)
    assert db.delete_user(conn, db.get_user_by_email(conn, "ann@example.com")["id"])
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    conn.close()


def test_bad_notes_are_refused_with_a_reason(app, db_path):
    c = app.test_client()
    for data, words in [({"message": "   "}, "Write a few words"),
                        ({"message": "x" * 2001}, "longer than 2,000"),
                        ({"message": "hi", "reply_to": "not an email"}, "look right")]:
        r = c.post("/feedback", data={"csrf": token(c, "/feedback"), **data})
        assert r.status_code == 422 and words in r.get_data(as_text=True)
    assert c.post("/feedback", data={"message": "no token"}).status_code == 400
    assert rows(db_path) == []


def test_only_a_page_on_this_site_is_recorded():
    assert feedback.clean_page("/portfolio?x=1") == "/portfolio?x=1"
    for bad in ["https://evil.example/", "//evil.example", "javascript:alert(1)", "/a\nb", "\\evil", "", None]:
        assert feedback.clean_page(bad) is None


def test_at_most_five_an_hour(app, db_path):
    c = app.test_client()
    for i in range(feedback.PER_HOUR):
        assert c.post("/feedback", data={"csrf": token(c, "/feedback"), "message": f"note {i}"}).status_code == 302
    r = c.post("/feedback", data={"csrf": token(c, "/feedback"), "message": "one too many"})
    assert r.status_code == 422 and "a lot of feedback" in r.get_data(as_text=True)
    assert len(rows(db_path)) == feedback.PER_HOUR
