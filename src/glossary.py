"""Plain-English meanings for the words SGXray uses: the tap-a-term popups.

One place for every definition, so the dashboard, the Learn page and the explanations all say the
same thing. Each entry: the term as shown in the popup, a one- or two-sentence meaning, and a short
example. Keep them short: a popup is a reminder, not a lesson (the Learn page is for lessons).
"""

from markupsafe import Markup

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
    "a-year": ("Your return (a year, or so far)",
               "From a year of history: your return as one yearly rate (XIRR), counting WHEN each dollar went in or "
               "came out. Under a year: the plain total for the time you've held, because stretching a few months "
               "into a 'per year' figure exaggerates luck. Under a month: too soon to compare.",
               "+3% over 2 months is shown as +3% over 2 months, not as +19% a year."),
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
                     "shown by the solid light-blue line along the top of the X-ray chart.",
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
    "picks-alone": ("Your picks alone (TWR)",
                    "The time-weighted return: how your investments did, ignoring WHEN you added or took out money, "
                    "as if one dollar went in at the start and stayed. It's how funds and the STI report returns, "
                    "so it's the fair way to judge your picks.",
                    "A stock goes $100 -> $50 -> $100: TWR 0%, even if buying more at $50 made you money."),
    "day-change": ("Day's change",
                   "How much your holdings moved from the previous closing price to the latest one, in $ and %. "
                   "Buying or selling that day doesn't count, only price moves and dividends.",
                   "DBS closed $1.48 lower: 210 shares x -$1.48 = -$310.80."),
    "simple-return": ("Simple total return",
                      "Your total profit divided by all the money you've put in (every buy, fees included). "
                      "One plain percentage for the whole time, not a yearly rate.",
                      "+$11,517 profit on $15,207 put in = +75.7% over 2 years and 8 months."),
    "weight": ("Weight",
               "A stock's share of what your whole portfolio is worth. Weights add up to 100%.",
               "DBS worth $14,641 of a $22,695 portfolio = a 65% weight."),
    "periods": ("Period returns",
                "How much your investments grew over a set stretch (1 month, 3 months, this year, 1 year, or "
                "all the time), next to the STI ETF. Time-weighted, so deposits don't count as growth.",
                "Over the last year: you +25.3%, the STI ETF +19.2%."),
    "ytd": ("YTD (year to date)",
            "From the last closing price of last year to now.",
            "In November, YTD covers about 10 months."),
    "sold": ("Sold (closed position)",
             "A stock you've sold all your shares of. It leaves your holdings, but its realised profit and the "
             "dividends it paid still count in your total.",
             "Sold all 1,000 units: put in $1,980, got back $2,310 after fees = +$330 realised."),
    "week52": ("52-week range",
               "A stock's highest and lowest closing price over the last 52 weeks (one year), and where today's "
               "price sits between them. History, not a forecast.",
               "DBS: low $53.38, high $78.65, today $69.72, in the middle of its range."),
    # The reason words: what a cell says instead of a number (the page rule in NOTES.md).
    "pending": ("Pending",
                "Waiting for tonight's closing price. You bought a stock today, and SGX publishes its first "
                "closing price at about 5:45pm, so numbers that need that price fill in then.",
                "Bought OCBC this morning: worth and profit say pending until the evening price update."),
    "too-soon": ("Too soon",
                 "Not enough history yet to work this out fairly. Comparing returns needs at least a month, and "
                 "a period (like 1 year) needs that much history.",
                 "Bought 3 weeks ago: too soon to compare with the STI ETF. In a week it fills in."),
    "after-close": ("After today's close",
                    "A stock you bought today has no closing price yet. SGX closes at 5pm and SGXray gets the "
                    "price at about 5:45pm.",
                    "Bought DBS at 10am: its price shows after today's close."),
    "no-price": ("No price yet",
                 "SGXray hasn't saved a closing price for this stock yet, so numbers that need it (its worth, "
                 "profit and weight, and your totals) wait for it. Prices are saved by the daily price update, "
                 "after SGX closes at about 5:45pm.",
                 "Added Singapore Airlines this afternoon: its price comes with this evening's price update."),
    "no-chart": ("No price chart yet",
                 "A price chart is drawn from the closing prices SGXray has saved for a stock. This one has "
                 "none saved yet, so there's nothing to draw. The daily price update saves them after SGX "
                 "closes at about 5:45pm, and the chart appears after that.",
                 "Added Singapore Airlines this afternoon: its chart is ready after this evening's price update."),
    # ---- Learn page (w313) ----
    "emergency-fund": ("Emergency fund",
                       "Cash kept aside for surprises like losing your job or a big medical bill, so you never have "
                       "to sell investments at a bad time. MoneySense suggests 3 to 6 months of expenses (12 if "
                       "your income is irregular), in a savings account or Singapore Savings Bonds.",
                       "Spending $1,500 a month: an emergency fund of $4,500 to $9,000."),
    "expensive-debt": ("Expensive debt",
                       "Borrowing that charges a high interest rate, like an unpaid credit card bill. Paying it off "
                       "is a guaranteed 'return' that investing rarely beats.",
                       "A $2,000 card balance at 27.8% a year costs about $556 in a year if left unpaid."),
    "dip": ("A fall (drawdown)",
            "How far a portfolio dropped from its high point before climbing back. Falls are normal; "
            "selling during one is what turns a paper loss into a real one.",
            "$17,964 down to $15,197 is a $2,767 fall, about 15%."),
    "share": ("Share (stock)",
              "A small piece of ownership in a company. You get a part of its profits (as dividends) and its "
              "price moves with how the business and the market are doing.",
              "100 DBS shares = a tiny piece of DBS Group Holdings."),
    "reit": ("REIT",
             "A real estate investment trust: a trust that owns buildings (malls, offices, warehouses) and pays "
             "out most of the rent. To avoid tax at the trust level it must pay out at least 90% of its taxable "
             "income.",
             "CapitaLand Integrated Commercial Trust owns malls and offices like Raffles City."),
    "etf": ("ETF",
            "An exchange-traded fund: one fund that holds many companies, bought and sold like a single share.",
            "One STI ETF unit holds a slice of all 30 companies in the Straits Times Index."),
    "board-lot": ("Board lot",
                  "The usual trading size on SGX: 100 shares. You can also buy fewer (from 1 share) in SGX's "
                  "unit share market, which has fewer buyers and sellers.",
                  "DBS at $69.72: one board lot of 100 shares costs about $6,972 before fees."),
    "cdp": ("CDP account",
            "An account at The Central Depository, run by SGX, that holds your Singapore shares in your own name. "
            "Dividends go straight to your linked bank account, company letters come to you, and you can vote "
            "at meetings. You can keep it if you change brokers.",
            "Buy DBS through a CDP-linked broker: the shares show up under your name in your CDP statement."),
    "custodian": ("Custodian account",
                  "Your broker holds the shares for you, in the broker's (nominee's) name. You still own them, but "
                  "dividends and company letters come through the broker, voting is usually indirect, and moving "
                  "to another broker can cost a fee. Often cheaper per trade.",
                  "Many app-based brokers use custodian accounts; some can also link to your CDP."),
    "mas-directory": ("MAS Financial Institutions Directory",
                      "The Monetary Authority of Singapore's public list of every firm it licenses, and what each "
                      "is allowed to do. If a firm offering you an investment isn't on it, don't send money.",
                      "Search the firm's exact name on mas.gov.sg/directories before you pay anything."),
    "guaranteed-return": ("Guaranteed high returns",
                          "A promise of big, steady profits with little or no risk. Real investments can't promise "
                          "this: prices fall sometimes. It's the most common sign of a scam.",
                          "\"3% a month, guaranteed\" works out to about 43% a year, every year. Nothing real does that."),
    "commission": ("Broker commission",
                   "What your broker charges for each buy or sell: usually a percentage of the trade, with a minimum "
                   "fee per trade. On small trades the minimum is what you pay.",
                   "0.1% with a $10 minimum: a $500 trade still costs $10, which is 2%."),
    "sgx-fees": ("SGX fees",
                 "Small fees SGX adds to every trade: a clearing fee of 0.0325% and a trading access fee of 0.0075% "
                 "of the trade's value, plus 9% GST on them and on your broker's commission.",
                 "On a $10,000 trade: $3.25 + $0.75 = $4.00, plus about $0.36 GST."),
    "payment-date": ("Payment date",
                     "The day the dividend cash actually reaches you, usually a few weeks after the ex-date. The "
                     "company's announcement on SGX gives the exact date.",
                     "Ex-date in early May, cash in your bank account later in May."),
    "dividend-tax": ("Tax on dividends",
                     "Dividends from Singapore companies are tax-free for you: the company has already paid tax on "
                     "its profits. Many other countries take tax off dividends before they reach you.",
                     "DBS pays $100 of dividends: you get the full $100. A US company's $100 usually arrives as $70."),
    "inflation": ("Inflation",
                  "Prices rising over time, so the same dollar buys less each year. Cash kept for years quietly "
                  "loses spending power.",
                  "At 2% inflation, $10,000 buys about what $8,200 does today after 10 years."),
    "compounding": ("Compounding",
                    "Earning returns on your past returns, not just on the money you put in. The longer it runs, "
                    "the faster the pile grows.",
                    "$10,000 growing 6% a year: $17,900 after 10 years, $32,100 after 20."),
    "regular-investing": ("Investing every month",
                          "Putting in the same amount on a schedule, whatever the price. You buy more shares when "
                          "prices are low and fewer when they're high, and you never have to guess the right day.",
                          "$200 a month into the STI ETF, through a bank's regular savings plan."),
    "index-fund": ("Index fund",
                   "A fund that simply buys everything in an index instead of picking. Low cost, and it gets the "
                   "market's return, no better and no worse.",
                   "The STI ETF holds all 30 STI companies in the same proportions as the index."),
    "money-weighted": ("Money-weighted return",
                       "Your own return, counting when your money went in and out. It answers \"how did MY money "
                       "do?\" Also called XIRR.",
                       "Adding a lot of money just before a rise makes your money-weighted return look better."),
    "time-weighted": ("Time-weighted return",
                      "How your picks did, ignoring when you added or took out money, as if one dollar had stayed "
                      "in from the start. It's how funds report, so it's the fair way to compare picks.",
                      "Funds and the STI ETF report time-weighted returns."),
    "practice-cash": ("Pretend cash",
                      "The practice portfolio's money. You start with $10,000 of it; buys and their fees take it "
                      "away, sales and dividends add it back. It isn't real and can't be withdrawn.",
                      "Buy 100 DBS at $69.72: $6,972.00 plus $13.94 of fees, so $10,000 becomes $3,014.06."),
    "holding-type": ("Type",
                     "What kind of thing you own: shares in one company, a REIT (a trust that owns buildings), or "
                     "an ETF (one fund holding many companies). Each behaves differently in good and bad years.",
                     "DBS = shares in a company; CICT = a REIT; the STI ETF = an ETF."),
    "sector": ("Sector",
               "The industry a company is in, like banks, telecoms or property. Companies in the same sector "
               "often rise and fall together, because the same news hits them all.",
               "DBS, OCBC and UOB are all banks: an interest-rate cut affects all three."),
    "volatility": ("How bumpy (volatility)",
                   "How much a portfolio's value usually swings up and down, as a yearly figure. Bigger means a "
                   "rougher ride: larger rises and larger falls. It measures the bumps, not which way they go.",
                   "13.5% a year: as a rough guide, about two years in three end within 13.5% of an average year."),
    "below-high": ("Below its high",
                   "How far the portfolio is now under its best point so far, counting how the investments did "
                   "(money added or taken out doesn't count).",
                   "At its high it was 100; now it's 92: 8% below its high."),
    "in-the-news": ("In the news",
                    "Headlines that mention this stock, from CNA, The Business Times, The Straits Times and The Edge "
                    "Singapore. SGXray shows each headline as published, with a link to the full article: it "
                    "doesn't summarise or judge them. News often moves a price for a few days; the question is "
                    "whether it changes your reason for owning it.",
                    "A headline about a bank's quarterly results: read it, then reread your Why I bought note."),
    "per-stock": ("Per stock",
                  "This column only has a number for one stock at a time (its own shares, price, cost or "
                  "dividend per share), so a whole-portfolio total wouldn't mean anything. Each stock's "
                  "figure is in its row above.",
                  "DBS's $69.72 price plus CICT's $2.34 = $72.06, which isn't the price of anything."),
    "not-yet": ("Not yet",
                "SGXray hasn't saved any prices for the STI ETF yet, so there's nothing to compare you with. "
                "They come with the next price update.",
                "A brand-new copy of SGXray, before its first price update."),
    "difference": ("Difference vs the STI ETF",
                   "Your profit on a stock minus what the same money would have made in the STI ETF. "
                   "Positive = that pick helped you beat the market.",
                   "DBS made +$8,075; the same money in the STI ETF, +$4,660: +$3,415 difference."),
}


def button(key, text=None):
    """The tappable word itself: a quiet button that opens the meaning box for `key`. The term() macro
    in templates/_term.html and the "pending" number filters both use this, so every tappable word is
    built the same way. `text` is escaped, so it can never inject HTML."""
    shown = text if text is not None else entry(key)[0]
    return Markup(
        '<button class="term" type="button" popovertarget="term-{k}" data-term="{k}">{t}</button>'
    ).format(k=key, t=shown)


def entry(key):
    """(term, meaning, example) for a key. Raises KeyError for an unknown key, so a typo fails a test."""
    return TERMS[key]
