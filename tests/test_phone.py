"""Works well on phones (w307): every page has the phone menu, with every link a person can use."""

import re

from test_trades import app, db_path, downloads, signed_up  # noqa: F401  (fixtures)


def menu(page):
    m = re.search(r'<div class="nav-menu" id="nav-menu" popover>(.*?)</div>', page, re.S)
    assert m, "no phone menu"
    return m.group(1)


def test_every_page_has_a_menu_button_that_opens_the_menu(app):
    c = app.test_client()
    for path in ("/", "/demo", "/learn", "/learn/first-dollar", "/learn/ready", "/login", "/signup", "/forgot"):
        page = c.get(path).get_data(as_text=True)
        assert '<button class="nav-menu-btn" type="button" popovertarget="nav-menu">Menu</button>' in page, path
        menu(page)


def test_logged_out_the_menu_offers_learning_the_demo_and_logging_in(app):
    links = menu(app.test_client().get("/").get_data(as_text=True))
    for href in ('href="/"', 'href="/demo"', 'href="/learn"', 'href="/login"', 'href="/signup"'):
        assert href in links
    assert 'href="/portfolio"' not in links and "Log out" not in links


def test_logged_in_the_menu_reaches_every_page(app):
    c = signed_up(app)
    for path in ("/portfolio", "/practice", "/trades", "/account", "/learn"):
        links = menu(c.get(path).get_data(as_text=True))
        for href in ('href="/learn"', 'href="/portfolio"', 'href="/practice"', 'href="/trades"', 'href="/account"'):
            assert href in links, (path, href)
        assert "Log out" in links and 'name="csrf"' in links        # logging out is still a protected POST


def test_the_menu_marks_the_page_you_are_on(app):
    c = signed_up(app)
    assert 'href="/practice" aria-current="page">Practice' in menu(c.get("/practice/trades").get_data(as_text=True))
    assert 'href="/learn" aria-current="page">Learn' in menu(c.get("/learn/scams").get_data(as_text=True))
    assert menu(c.get("/trades").get_data(as_text=True)).count('aria-current="page"') == 1


def test_detailed_only_sections_are_marked_and_the_essentials_are_not(app):
    from test_trades import add
    c = signed_up(app)
    add(c)
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'data-view-switch hidden' in page and 'js/view.js' in page          # only appears once its script runs
    for marked in ('aria-labelledby="risk-title" data-detail', 'aria-labelledby="vs-title" data-detail',
                   'aria-labelledby="yields-title" data-detail', 'aria-labelledby="forecast-title" data-detail'):
        assert marked in page, marked
    for essential in ('aria-labelledby="holdings-title">', 'aria-labelledby="alloc-title">'):
        assert essential in page, essential                                      # never hidden in Simple


def test_an_empty_portfolio_has_no_view_switch(app):
    assert "data-view-switch" not in signed_up(app).get("/portfolio").get_data(as_text=True)


def test_empty_screens_get_a_decorative_trace_that_hides_from_screen_readers(app):
    page = signed_up(app).get("/portfolio").get_data(as_text=True)                # no trades yet
    assert '<svg class="empty-trace"' in page and 'aria-hidden="true" focusable="false"' in page
    assert "<text" not in page.split('class="empty-trace"')[1].split("</svg>")[0]   # no numbers or labels


def test_pages_with_data_have_no_decorative_trace(app):
    from test_trades import add
    c = signed_up(app)
    add(c)
    assert "empty-trace" not in c.get("/portfolio").get_data(as_text=True)


def test_portfolio_pages_have_the_sections_menu_with_back_to_top(app):
    from test_trades import add
    c = signed_up(app)
    add(c)
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'popovertarget="jump-menu">Sections</button>' in page and 'data-jump="top"' in page
    assert 'data-jump="holdings-title"' in page and "js/jump.js" in page


def test_the_note_boxes_offer_a_tab_suggestion(app):
    page = signed_up(app).get("/trades").get_data(as_text=True)
    assert "data-note-suggest" in page and "press Tab for an example" in page and "js/notes.js" in page


def test_the_account_page_has_the_light_switch_and_login_doesnt(app):
    c = signed_up(app)
    assert page_has_switch(c.get("/account").get_data(as_text=True))
    assert not page_has_switch(app.test_client().get("/login").get_data(as_text=True))


def page_has_switch(page):
    return page.count("data-light-switch") == 2
