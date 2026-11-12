"""Where your money is (s02): split by type and sector, with warnings at 25% in one company or 50% in one sector."""

import math

import pandas as pd
import pytest

import allocation
from test_trades import add, app, db_path, downloads, signed_up  # noqa: F401  (fixtures)

INFO = {"D05.SI": {"name": "DBS Group Holdings", "type": "stock", "sector": "Banks"},
        "O39.SI": {"name": "OCBC", "type": "stock", "sector": "Banks"},
        "C38U.SI": {"name": "CapitaLand Integrated Commercial Trust", "type": "reit", "sector": "Retail and office"},
        "ES3.SI": {"name": "SPDR Straits Times Index ETF", "type": "etf", "sector": "Singapore market (STI)"},
        "Z74.SI": {"name": "Singtel", "type": "stock", "sector": "Telecoms"}}


def held(**values):
    return pd.DataFrame([{"ticker": t, "shares": 100, "value": v} for t, v in values.items()])


def test_the_split_adds_up_and_is_biggest_first():
    a = allocation.split(held(**{"D05.SI": 6000, "C38U.SI": 1000, "ES3.SI": 3000}), INFO)
    assert a["total"] == 10_000
    assert [(g["label"], round(g["share"], 2)) for g in a["by_type"]] == \
        [("Shares in companies", 0.6), ("ETFs (funds)", 0.3), ("REITs", 0.1)]
    assert [g["label"] for g in a["by_sector"]] == ["Banks", "Whole market (index fund)", "Retail and office"]
    assert math.isclose(sum(g["share"] for g in a["by_sector"]), 1.0)


def test_one_company_over_25_percent_gets_a_warning_and_at_25_it_doesnt():
    over = allocation.split(held(**{"D05.SI": 2600, "Z74.SI": 2500, "C38U.SI": 2400, "ES3.SI": 2500}), INFO)
    assert len(over["warnings"]) == 1 and over["warnings"][0].startswith("DBS Group Holdings is 26%")
    level = allocation.split(held(**{"D05.SI": 2500, "Z74.SI": 2500, "C38U.SI": 2500, "ES3.SI": 2500}), INFO)
    assert level["warnings"] == []


def test_an_etf_never_counts_as_one_company():
    a = allocation.split(held(**{"ES3.SI": 9000, "D05.SI": 1000}), INFO)          # 90% in the STI ETF
    assert a["warnings"] == []
    assert a["top"]["name"] == "DBS Group Holdings"


def test_one_sector_over_half_gets_its_own_warning():
    # Two banks under 25% each never trip the company rule; together they trip the sector rule once over 50%.
    a = allocation.split(held(**{"D05.SI": 2400, "O39.SI": 2400, "Z74.SI": 2400, "ES3.SI": 2800}), INFO)
    assert a["warnings"] == []                                                      # banks 48%: fine
    b = allocation.split(held(**{"D05.SI": 2500, "O39.SI": 2600, "Z74.SI": 2400, "ES3.SI": 2500}), INFO)
    assert any(w.startswith("The banks sector is 51%") for w in b["warnings"])


def test_a_stock_with_no_price_is_left_out_and_said_so():
    a = allocation.split(held(**{"D05.SI": 1000, "O39.SI": float("nan")}), INFO)
    assert a["missing"] == ["OCBC"] and a["total"] == 1000
    from explain import explain_allocation
    assert "Not counted yet: OCBC, which has no closing price saved" in explain_allocation(a).text


def test_nothing_held_means_no_section():
    assert allocation.split(held(**{"D05.SI": 1000}).assign(shares=0), INFO) is None


def test_the_demo_style_portfolio_shows_the_section_with_its_warnings(app):
    c = signed_up(app)
    add(c)                                                     # 100 DBS: 100% one company, 100% banks
    page = c.get("/portfolio").get_data(as_text=True)
    assert 'id="alloc-title">Where your money is' in page
    assert "DBS Group Holdings is 100% of what you hold" in page
    assert "The banks sector is 100% of what you hold" in page
    assert 'href="/learn/risk-and-time">Why spreading out helps' in page
    from test_page_rules import check_page_rules
    check_page_rules(page)
