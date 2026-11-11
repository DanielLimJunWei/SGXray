"""'Am I ready to start?' (w321): eight basics people usually have in place before investing.

A checklist, never a verdict. It says what's in place and what usually comes first, with a link to the
lesson that explains why. It never says "you're ready" or "you should invest": that's the person's own
decision (MAS: general education isn't financial advice).

The answers are personal (savings, debts, insurance), so nothing here is saved anywhere. The form is
posted once, the result is shown, and the answers are gone.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    key: str
    ask: str
    options: tuple          # ((value, label), ...) in the order shown
    good: frozenset         # the values that count as "in place"
    title: str              # short name in the result
    yes: str                # one line when it's in place
    no: str                 # one line when it usually comes first
    lesson: str             # the lesson slug that explains it ("" for none)
    lesson_title: str
    outside: str = ""       # an outside page instead of (or as well as) a lesson


QUESTIONS = [
    Question(
        "fund", "About how many months of your usual expenses do you have saved in cash?",
        (("none", "None yet"), ("under3", "Less than 3 months"), ("3to6", "3 to 6 months"),
         ("6to12", "6 to 12 months"), ("over12", "More than 12 months")),
        frozenset({"3to6", "6to12", "over12"}),
        "An emergency fund",
        "You have a cushion, so a surprise bill won't force you to sell shares at a bad time.",
        "MoneySense suggests 3 to 6 months of expenses in cash first, so a surprise never forces you to sell.",
        "first-dollar", "Before your first dollar"),
    Question(
        "debt", "Do you have an unpaid credit card balance or a personal loan?",
        (("yes", "Yes"), ("no", "No")),
        frozenset({"no"}),
        "No expensive debt",
        "Nothing is quietly charging you more than investing is likely to earn.",
        "Card interest is about 28% a year. Paying it off first is a guaranteed win investing rarely beats.",
        "first-dollar", "Before your first dollar"),
    Question(
        "cover", "If you had a big medical bill or lost your income for a few months, would it be covered?",
        (("yes", "Yes, by insurance or savings"), ("partly", "Partly"), ("no", "No"), ("unsure", "I'm not sure")),
        frozenset({"yes"}),
        "Protection",
        "A health scare or a gap in income wouldn't wipe out your plans.",
        "MoneySense puts protecting yourself before investing. MediShield Life is a start; check what else you'd need.",
        "", "", "https://www.moneysense.gov.sg/"),
    Question(
        "when", "When might you need the money you'd invest?",
        (("soon", "Within a year"), ("mid", "In 1 to 5 years"), ("long", "Not for 5 years or more")),
        frozenset({"long"}),
        "Money you can leave alone",
        "Five years or more gives prices time to recover from falls.",
        "Money needed within five years belongs in savings: a fall could hit just when you need it.",
        "risk-and-time", "Risk and time"),
    Question(
        "goal", "Do you know what this money is for?",
        (("yes", "Yes, a clear goal"), ("rough", "Roughly"), ("no", "Not really")),
        frozenset({"yes", "rough"}),
        "A goal",
        "A goal tells you how long you can wait and how much risk makes sense.",
        "A goal (retirement, a flat in 10 years) decides how long you can leave money in, and what to do in a fall.",
        "risk-and-time", "Risk and time"),
    Question(
        "fall", "If your shares fell {fall} in two weeks, what would you most likely do?",
        (("sell", "Sell everything to stop the loss"), ("hold", "Worry, but hold on"),
         ("calm", "Hold calmly, or buy more")),
        frozenset({"hold", "calm"}),
        "Ready for a fall",
        "Falls happen. Holding through them is what lets time do its work.",
        "Selling in a fall turns a paper loss into a real one. The demo fell like this and recovered.",
        "risk-and-time", "Risk and time"),
    Question(
        "costs", "Do you know your broker's minimum fee per trade, and whether it uses CDP or a custodian account?",
        (("both", "Yes, both"), ("one", "One of them"), ("neither", "Not yet")),
        frozenset({"both"}),
        "Knowing your costs",
        "You know what each trade costs and where your shares will be kept.",
        "On small trades the minimum fee decides the cost, and the account type decides how dividends reach you.",
        "fees", "What fees really cost"),
    Question(
        "scam", "Before paying anyone to invest for you, would you check MAS's Financial Institutions Directory?",
        (("yes", "Yes"), ("didnt", "I didn't know about it"), ("no", "Probably not")),
        frozenset({"yes"}),
        "Scam-proofing",
        "Checking MAS's directory first stops most investment scams before they start.",
        "Scams are the biggest risk for beginners. A firm not on MAS's directory shouldn't get your money.",
        "scams", "Spotting investment scams"),
]

BY_KEY = {q.key: q for q in QUESTIONS}

# With income that goes up and down (freelance, commission, gig work), MoneySense suggests 12 months, not 3 to 6.
IRREGULAR_GOOD = frozenset({"over12"})
IRREGULAR_NO = ("Your income goes up and down, so MoneySense suggests about 12 months of expenses in cash "
                "before investing.")
IRREGULAR_YES = "You have about a year's cushion, which suits an income that goes up and down."


def answers_from(form):
    """Only the allowed answer for each question; anything else (missing, tampered, too long) is None.
    The form's text is never stored or logged: this dict is used once and thrown away."""
    out = {}
    for q in QUESTIONS:
        value = str(form.get(q.key, ""))[:16]
        out[q.key] = value if value in {v for v, _ in q.options} else None
    out["irregular"] = str(form.get("irregular", ""))[:4] == "yes"      # a tick box: only "yes" counts
    return out


def check(answers):
    """The result: one row per question, each "in place", "first" (usually sorted first) or "skipped".
    Returns {"rows": [...], "in_place": n, "skipped": n, "total": 8}."""
    rows = []
    for q in QUESTIONS:
        a = answers.get(q.key)
        good, yes, no = q.good, q.yes, q.no
        if q.key == "fund" and answers.get("irregular"):
            good, yes, no = IRREGULAR_GOOD, IRREGULAR_YES, IRREGULAR_NO
        state = "skipped" if a is None else ("in place" if a in good else "first")
        label = dict(q.options).get(a, "")
        rows.append({"key": q.key, "title": q.title, "state": state, "answer": label,
                     "why": (yes if state == "in place" else no) if state != "skipped" else "Not answered.",
                     "lesson": q.lesson,
                     "lesson_title": q.lesson_title, "outside": q.outside})
    return {"rows": rows, "in_place": sum(r["state"] == "in place" for r in rows),
            "skipped": sum(r["state"] == "skipped" for r in rows), "total": len(rows)}
