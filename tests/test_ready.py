"""'Am I ready to start?' (w321): a checklist, never a verdict, and nothing anyone answers is saved."""

import re

import db
import readiness
from test_learn import app, db_path, load_demo, signed_up, token  # noqa: F401  (fixtures)

ALL_GOOD = {"fund": "3to6", "debt": "no", "cover": "yes", "when": "long", "goal": "yes", "fall": "hold",
            "costs": "both", "scam": "yes"}


def send(c, answers):
    return c.post("/learn/ready", data={"csrf": token(c, "/learn/ready"), **answers})


def text(r):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.get_data(as_text=True)))


def test_the_page_asks_all_eight_questions_without_logging_in(app):
    r = app.test_client().get("/learn/ready")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    page = r.get_data(as_text=True)
    assert page.count('<fieldset class="ready-q">') == 8
    assert 'method="post"' in page and 'name="irregular"' in page


def test_everything_in_place_is_a_checklist_not_a_verdict(app):
    page = text(send(app.test_client(), ALL_GOOD)).lower()
    assert "8 of 8 in place" in page
    for verdict in ("you're ready", "you are ready", "ready to invest", "you should invest", "score", "grade"):
        assert verdict not in page.replace("am i ready to start", ""), verdict
    assert "only you can decide when to start" in page


def test_gaps_say_usually_sorted_first_and_link_their_lesson(app):
    r = send(app.test_client(), {**ALL_GOOD, "debt": "yes", "scam": "didnt"})
    page = r.get_data(as_text=True)
    assert "6 of 8 in place" in text(r)
    assert page.count("Usually sorted first") == 2
    assert 'href="/learn/first-dollar"' in page and 'href="/learn/scams"' in page


def test_skipped_questions_are_counted_and_say_so(app):
    r = send(app.test_client(), {"fund": "over12", "debt": "no"})
    page = text(r)
    assert "2 of 8 in place" in page and "6 skipped" in page and "Not answered." in page


def test_irregular_income_needs_twelve_months(app):
    c = app.test_client()
    page = send(c, {**ALL_GOOD, "fund": "3to6", "irregular": "yes"}).get_data(as_text=True)
    assert "7 of 8 in place" in text(send(c, {**ALL_GOOD, "fund": "3to6", "irregular": "yes"}))
    assert "about 12 months" in page
    assert "8 of 8 in place" in text(send(c, {**ALL_GOOD, "fund": "over12", "irregular": "yes"}))


def test_tampered_answers_are_ignored(app):
    r = send(app.test_client(), {**ALL_GOOD, "debt": "<script>x</script>", "fund": "over12" * 50})
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and "<script>x</script>" not in page
    assert "6 of 8 in place" in text(r) and "2 skipped" in text(r)


def test_the_answers_come_back_ticked_so_you_can_change_one(app):
    page = send(app.test_client(), ALL_GOOD).get_data(as_text=True)
    assert 'name="debt" value="no" checked' in page


def test_nothing_anyone_answers_is_saved(app, db_path):
    """Count every row in every table before and after: answering changes nothing, logged in or not."""
    def counts():
        conn = db.get_connection(db_path)
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        out = {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
        conn.close()
        return out
    ann = signed_up(app)
    before = counts()
    send(ann, {**ALL_GOOD, "debt": "yes"})
    send(app.test_client(), ALL_GOOD)
    assert counts() == before


def test_answers_never_go_in_the_address(app):
    page = app.test_client().get("/learn/ready").get_data(as_text=True)
    assert re.search(r'<form class="ready-form" method="post" action="/learn/ready#result"', page)


def test_the_form_needs_its_token(app):
    assert app.test_client().post("/learn/ready", data=ALL_GOOD).status_code == 400


def test_the_fall_question_uses_the_demos_real_fall(app, db_path):
    load_demo(db_path)                                   # 7,800 down to 6,200: a 21% fall
    page = app.test_client().get("/learn/ready").get_data(as_text=True)
    assert "fell 21% in two weeks" in page and "3 February 2025" in page


def test_the_learn_page_and_the_last_lesson_lead_here(app):
    c = app.test_client()
    assert 'href="/learn/ready"' in c.get("/learn").get_data(as_text=True)
    assert "Done · next: Am I ready to start?" in c.get("/learn/reading-sgxray").get_data(as_text=True)


def test_every_question_has_a_lesson_or_an_outside_link():
    from lessons import BY_SLUG
    for q in readiness.QUESTIONS:
        assert q.lesson in BY_SLUG or q.outside.startswith("https://"), q.key
        assert q.good <= {v for v, _ in q.options}, q.key
