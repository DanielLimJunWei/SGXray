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
    "difference": ("Difference vs the STI ETF",
                   "Your profit on a stock minus what the same money would have made in the STI ETF. "
                   "Positive = that pick helped you beat the market.",
                   "DBS made +$8,075; the same money in the STI ETF, +$4,660: +$3,415 difference."),
}


def entry(key):
    """(term, meaning, example) for a key. Raises KeyError for an unknown key, so a typo fails a test."""
    return TERMS[key]
