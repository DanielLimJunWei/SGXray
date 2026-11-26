"""The little chart on each login / account board (src/film.py): every board its own shape, all inside the film."""

import film
from test_trades import app, db_path, downloads  # noqa: F401  (fixtures)


def heights(path):
    return [float(p.split()[1]) for p in path.replace("M", "L").split("L") if p.strip()]


def test_every_shape_fits_the_film_and_each_is_different():
    lines = set()
    for kind in film.SHAPES:
        s = film.shape(kind)
        ys = heights(s["line"])
        assert len(ys) == film.N and all(0 <= y <= 120 for y in ys), kind
        assert all(120 - 16 <= y <= 120 for _, y in s["bars"]), kind
        lines.add(s["line"])
    assert len(lines) == len(film.SHAPES)


def test_login_rises_and_forgot_falls():
    up, down = heights(film.shape("rise")["line"]), heights(film.shape("fall")["line"])
    assert up[-1] < up[0] and down[-1] > down[0]           # smaller y is higher on the film


def test_an_unknown_kind_falls_back_to_the_rising_line():
    assert film.shape("nonsense")["line"] == film.shape("rise")["line"]


def test_each_board_shows_its_own_chart(app):
    c = app.test_client()
    for page, kind in [("/login", "rise"), ("/forgot", "fall"), ("/signup", "pulse"), ("/reset/not-a-real-link", "flat")]:
        html = c.get(page, follow_redirects=True).get_data(as_text=True)
        assert f'class="film-chart film-kind-{kind}"' in html, page
