"""Plain-English meanings for the words SGXray uses: the tap-a-term popups.

One place for every definition, so the dashboard, the Learn page and the explanations all say the
same thing. Each entry: the term as shown in the popup, a one- or two-sentence meaning, and a short
example. Keep them short: a popup is a reminder, not a lesson (the Learn page is for lessons).
"""

TERMS = {
    "worth": ("Worth now",
              "What everything you hold would sell for at the latest closing prices.",
              "200 DBS shares at a $69.72 close = $13,944."),
    "closing-price": ("Closing price",
                      "The last traded price at the end of a trading day. SGXray uses closing prices, so numbers "
                      "change once a day, not every second.",
                      "DBS closed at $69.72 on 6 November."),
    "total-profit": ("Total profit",
                     "Everything you've made or lost: unrealised profit + realised profit + dividends.",
                     "+$9,056 unrealised + $278 realised + $2,183 dividends = +$11,517."),
    "unrealised": ("Unrealised profit",
                   "Profit on shares you still hold: what they're worth now minus what they cost. It's only on "
                   "paper until you sell, and changes every day.",
                   "1,200 C38U units cost $2,352 and are worth $2,808: +$456 unrealised."),
    "realised": ("Realised profit",
                 "Profit locked in by selling: what you got for the shares, minus fees, minus what they cost you.",
                 "Sold 800 C38U at $2.32 that cost $1.96 each: $1,856 - $10 - $1,568 = +$278."),
    "dividend": ("Dividend",
                 "Cash a company pays you for each share you own, usually from its profits. Not guaranteed. "
                 "A REIT's dividend is called a distribution.",
                 "DBS pays $0.75 a share; 210 shares = $157.50."),
    "ex-date": ("Ex-dividend date",
                "The cut-off for a dividend: you must own the shares BEFORE this date to be paid. Buy on or after it "
                "and the seller gets that dividend.",
                "Ex-date 5 April: owners on 4 April are paid; buyers on 5 April aren't."),
    "avg-cost": ("Average cost",
                 "What each share cost you on average, fees included: total cost divided by shares held. "
                 "It's also your break-even price.",
                 "Bought DBS at two prices: $7,907 for 210 shares = $37.65 a share."),
    "cost": ("Cost",
             "What you paid for the shares you still hold, fees included.",
             "100 shares at $34.62 + $10 fees = $3,472."),
    "shares": ("Shares (units)",
               "How many pieces of the company you own. For REITs and ETFs they're called units.",
               "Owning 1,200 units of CapitaLand Integrated Commercial Trust."),
    "sti-etf": ("STI ETF",
                "One fund that holds the 30 biggest companies on the Singapore Exchange. SGXray puts your money into "
                "it on paper, on the same days, to show what simply buying 'the market' would have done.",
                "ES3.SI (SPDR Straits Times Index ETF)."),
    "a-year": ("A year (XIRR)",
               "Your return turned into one yearly rate, counting WHEN each dollar went in or came out, so money "
               "added recently isn't treated as if it had been there from the start.",
               "$1,000 in, $1,100 back a year later = +10% a year."),
    "price-gains": ("Price gains",
                    "What price changes have added on top of the money you put in (or taken away, if prices fell). "
                    "Not counting dividends.",
                    "Put in $13,361; shares now worth $22,695 = +$9,334 of price gains."),
    "money-in": ("Your own money (money in)",
                 "What you paid for buys minus what you got back from sales. It was yours to begin with, "
                 "so it isn't profit.",
                 "Bought $15,207, sold $1,846 back = $13,361 of your own money in."),
    "yield": ("Dividend yield",
              "A year's dividends per share divided by today's price: what a new buyer would earn in dividends "
              "a year, if payouts stay the same.",
              "$3.18 a year at a $69.72 price = 4.56%."),
    "yield-on-cost": ("Yield on cost",
                      "The same dividends divided by what YOU paid. High if you bought cheaply, but it says nothing "
                      "about whether the stock is a good buy today.",
                      "$3.18 a year on your $37.65 cost = 8.45%."),
    "forecast": ("Dividend forecast",
                 "An estimate: last year's dividends, assumed to come again on the shares you hold now. "
                 "Companies can raise, cut or skip them.",
                 "About $973 expected over the next 12 months."),
    "ticker": ("Stock code (ticker)",
               "The short code a stock trades under. \".SI\" at the end means it's listed on the Singapore Exchange.",
               "D05.SI = DBS; C38U.SI = CapitaLand Integrated Commercial Trust; ES3.SI = the STI ETF."),
    "per-share": ("Per share",
                  "The dividend paid for EACH share (or unit) you own. Multiply it by your shares to get your cash.",
                  "$0.75 per share x 210 DBS shares = $157.50."),
    "per-share-12m": ("Paid a share, 12 months",
                      "All the dividends one share paid over the last 12 months, added up. Many SGX stocks pay "
                      "two or four times a year.",
                      "DBS paid four times: about $3.18 a share in total."),
    "income-12m": ("A year's income",
                   "What the last 12 months of dividends would pay on the shares you hold now: paid a share x your shares.",
                   "$3.18 a share x 210 DBS shares = $667.80."),
    "expected": ("Expected (dividend)",
                 "The cash you'd get if the stock pays the same as last time: per share x the shares you hold now. "
                 "An estimate, not a promise.",
                 "$0.75 x 210 shares = about $157.50."),
    "expected-date": ("Expected around",
                      "A guess at the next ex-date: one year after the last one. The company announces the real "
                      "date shortly before.",
                      "Last ex-date 13 November 2025, so expected around 13 November 2026."),
    "your-profit": ("Your profit (one stock)",
                    "Everything that stock has given you: what it's worth now + money from selling it + its "
                    "dividends - what you paid for it.",
                    "DBS: +$8,075 so far."),
    "same-money-sti": ("Same money in the STI ETF",
                       "What you'd have made if every dollar you put into that stock had gone into the STI ETF "
                       "instead, on the same days, with the same fees.",
                       "The money you put into DBS would have made +$4,660 in the STI ETF."),
    "all-together": ("All together",
                     "Your own money + price gains + dividends: everything your investing has given you so far, "
                     "the top edge of the X-ray chart.",
                     "$13,361 + $9,334 + $2,183 = $24,878."),
    "buy": ("Buy",
            "A day you bought shares. On the chart it sits on that day's closing price; what you actually paid "
            "can be a little different, because you bought during the day.",
            "Bought 100 DBS at $34.62 on 15 March 2024; it closed at $34.67."),
    "sell": ("Sell",
             "A day you sold shares. Selling locks in (realises) the profit or loss on those shares.",
             "Sold 800 C38U units at $2.32 on 14 November 2025."),
    "avg-cost-line": ("Your average cost (dashed line)",
                      "What each share has cost you on average, fees included, over time. It steps when you buy, "
                      "sell or get bonus shares. Price above it = a profit on paper; below it = a loss on paper.",
                      "DBS: $34.72 after the first buy, $31.56 after the 1-for-10 bonus issue, $37.65 after the second buy."),
    "price-line": ("Closing price (the line)",
                   "The stock's price at the end of each trading day. It doesn't include dividends.",
                   "DBS closed at $69.72 on 6 November 2026."),
    "difference": ("Difference vs the STI ETF",
                   "Your profit on a stock minus what the same money would have made in the STI ETF. "
                   "Positive = that pick helped you beat the market.",
                   "DBS made +$8,075; the same money in the STI ETF, +$4,660: +$3,415 difference."),
}


def entry(key):
    """(term, meaning, example) for a key. Raises KeyError for an unknown key, so a typo fails a test."""
    return TERMS[key]
