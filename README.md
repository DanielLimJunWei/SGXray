# SGXray

**See inside your portfolio.** A learning site and portfolio tracker for beginner investors in Singapore:
SGX stocks, REITs and ETFs, measured against the STI, with every number explained in plain English.

## What it does

- **Learn first:** 9 short lessons taught with a demo portfolio's real numbers, an "Am I ready to start?" check,
  and a tap-to-explain glossary.
- **Track your portfolio:** add trades (or "a stock I already own"), monthly savings plans, and notes on why you
  bought. Splits, bonus issues and dividends are handled.
- **The X-ray:** what you put in, price gains and dividends over time; your return as both money-weighted (XIRR)
  and time-weighted; and the same money in the STI ETF, side by side.
- **Explained everywhere:** each figure has "What does this mean?", "Watch out" and "Going well" notes.
- **Practice portfolio:** pretend money at real closing prices, with real broker fees.
- **Market today:** Singapore business headlines from credible publishers, matched to SGX companies.
- **Yours to keep or delete:** download your data or delete your account at any time.

## Run it on your computer

```
python -m pip install -r requirements.txt
python src/importer.py data/demo_trades.csv    # the demo portfolio
python src/market.py                           # prices and dividends from Yahoo Finance
python -m flask --app app run --debug
```

Then open http://127.0.0.1:5000. New closing prices arrive by themselves after about 5:45pm Singapore time.

Tests: `python -m pip install -r requirements-dev.txt`, then `python -m pytest`.

## How it's built

Python, Flask, SQLite and pandas, with plain HTML, CSS and JavaScript (no build step).

| Folder | What's in it |
|---|---|
| `app.py` | The web app: pages, log-in and security headers |
| `src/` | The calculations (portfolio, performance, history, income, risk), data downloads and the database |
| `templates/`, `static/` | The pages, styles and scripts |
| `tests/` | Over 600 tests, including attack tests and calculations checked against outside references |
| `docs/` | [Design and calculation notes](docs/notes.md) and the [security audit record](docs/security-audits.md) |

Security: see [SECURITY.md](SECURITY.md).

## Disclaimer

SGXray is educational, not financial advice. Past returns don't predict future ones. Prices are end-of-day
closes from Yahoo Finance. Not affiliated with or endorsed by Singapore Exchange Limited.
