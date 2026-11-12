"""Where your money is (s02): your holdings split by type and by sector, with calm warnings when too much
sits in one place.

The warnings follow a common rule of thumb for beginners (chosen 12 Nov 2026):
- one company over 25% of what you hold. ETFs never count as "one company": they're already spread out.
- one sector over 50%.
Everything SGXray tracks is listed in Singapore, so "it's all Singapore" is true for everyone; that's a note
in the explanation, not a warning. Education, never "sell this".
"""

COMPANY_LIMIT = 0.25
SECTOR_LIMIT = 0.50

TYPE_LABELS = {"stock": "Shares in companies", "reit": "REITs", "etf": "ETFs (funds)"}
INDEX_SECTOR = "Whole market (index fund)"      # an ETF like the STI ETF holds many sectors at once


def split(positions_df, instruments):
    """By type and by sector, biggest first, from the positions table.

    instruments: {ticker: {"name", "type", "sector"}}.
    Returns {"by_type": [...], "by_sector": [...], "total", "missing": [names with no price yet],
    "warnings": [...], "top": the biggest single company (not an ETF) or None}, or None if nothing is held.
    Each row: {"label", "kind", "value", "share"}.
    """
    held = positions_df[positions_df["shares"] > 0] if positions_df is not None else None
    if held is None or held.empty:
        return None
    rows, missing = [], []
    for r in held.to_dict("records"):
        info = instruments.get(r["ticker"], {})
        name = info.get("name") or r["ticker"]
        if r["value"] != r["value"]:                  # NaN: no price yet, so it can't be counted
            missing.append(name)
            continue
        kind = info.get("type") or "stock"
        sector = INDEX_SECTOR if kind == "etf" else (info.get("sector") or "Other")
        rows.append({"ticker": r["ticker"], "name": name, "kind": kind, "sector": sector, "value": float(r["value"])})
    total = sum(r["value"] for r in rows)
    if not rows or not total:
        return {"by_type": [], "by_sector": [], "total": 0.0, "missing": missing, "warnings": [], "top": None}

    def group(key, label):
        sums = {}
        for r in rows:
            sums.setdefault(r[key], {"label": label(r), "kind": r[key], "value": 0.0})["value"] += r["value"]
        out = sorted(sums.values(), key=lambda g: -g["value"])
        for g in out:
            g["share"] = g["value"] / total
        return out

    by_type = group("kind", lambda r: TYPE_LABELS.get(r["kind"], r["kind"]))
    by_sector = group("sector", lambda r: r["sector"])
    companies = sorted((r for r in rows if r["kind"] != "etf"), key=lambda r: -r["value"])
    top = dict(companies[0], share=companies[0]["value"] / total) if companies else None

    warnings = []
    for r in companies:
        share = r["value"] / total
        if share > COMPANY_LIMIT:
            warnings.append(f"{r['name']} is {share:.0%} of what you hold. A bad year for that one company "
                            f"would move a big part of your money. A common rule of thumb for beginners is "
                            f"no more than about {COMPANY_LIMIT:.0%} in any one company.")
    for g in by_sector:
        if g["kind"] != INDEX_SECTOR and g["share"] > SECTOR_LIMIT:
            warnings.append(f"The {g['label'].lower()} sector is {g['share']:.0%} of what you hold, so one "
                            f"industry's bad news would hit most of your portfolio at once. Spreading across "
                            f"sectors (or an index fund) softens that.")
    return {"by_type": by_type, "by_sector": by_sector, "total": total, "missing": missing,
            "warnings": warnings, "top": top}
