"""The little chart on each login / account board's film (templates/_lightbox.html).

Every board shows a price line like a real stock chart (a blue line, an amber average, a faint fill and small bars
along the bottom), all in the same colours. Each has its own run of peaks and drops, so no two boards look alike:

    rise      log in             the demo portfolio's real monthly values: a climb
    fall      forgot password    a slide, with bounces on the way down
    pulse     sign up            a climb, a sharp drop, and a recovery to new highs
    wave      account            choppy and sideways, with one peak in the middle
    steps     change password    a steady climb with a pullback two-thirds in
    recover   new password       a fall, a bottom, then a recovery
    flat      expired link       flat and choppy, going nowhere
    fade      delete account     a peak early on, then a long, slow decline

They're decoration (aria-hidden): no numbers are read from them. Each line is a fixed random walk (the same seed every
time, so the page never changes), steered by a rough plan of where it should go.
"""

import random

N = 33                       # points: x = 0, 12.5, ... 400
STEP = 400 / (N - 1)
TOP, BOTTOM = 15.0, 117.0    # the highest and lowest the line goes, as on the log in board

# The demo portfolio's value, month by month, as heights on the film (120 = bottom). Unchanged from the original.
_RISE = [118.4, 117.1, 116.3, 99.0, 97.7, 81.3, 79.6, 80.3, 77.9, 77.4, 76.4, 75.1, 52.8, 56.0, 53.2, 52.1, 48.1,
         43.0, 42.1, 38.3, 45.2, 42.6, 38.7, 39.7, 41.3, 38.0, 33.1, 29.5, 18.8, 14.8, 15.6, 20.8, 24.5]


def _walk(seed, plan):
    """A price-like line: from `plan`, a few (position 0-1, level 0-1) points it should pass near, joined up, plus
    day-to-day noise and the odd jump. Returned as film heights (smaller = higher on the film)."""
    rng = random.Random(seed)
    values, noise = [], 0.0
    for i in range(N):
        t = i / (N - 1)
        for (t0, v0), (t1, v1) in zip(plan, plan[1:]):
            if t0 <= t <= t1:
                target = v0 + (v1 - v0) * (t - t0) / (t1 - t0)
                break
        noise = noise * 0.55 + rng.uniform(-0.06, 0.06) + (rng.choice([-0.12, 0.12]) if rng.random() < 0.08 else 0)
        values.append(target + noise)
    # Levels map straight onto the film (0 = bottom, 1 = top), so a sideways plan stays sideways; never off the film.
    return [round(min(BOTTOM, max(TOP, BOTTOM - v * (BOTTOM - TOP))), 1) for v in values]


PLANS = {
    "fall": (7, [(0, 0.9), (0.3, 0.75), (0.45, 0.8), (0.75, 0.35), (0.85, 0.45), (1, 0.1)]),
    "pulse": (11, [(0, 0.2), (0.45, 0.75), (0.55, 0.3), (1, 0.95)]),
    "wave": (23, [(0, 0.4), (0.3, 0.5), (0.5, 0.95), (0.7, 0.45), (1, 0.55)]),
    "steps": (5, [(0, 0.1), (0.6, 0.85), (0.72, 0.6), (1, 0.95)]),
    "recover": (13, [(0, 0.85), (0.45, 0.1), (0.55, 0.2), (1, 0.8)]),
    "flat": (31, [(0, 0.5), (0.3, 0.6), (0.6, 0.4), (1, 0.55)]),
    "fade": (17, [(0, 0.5), (0.2, 0.95), (0.5, 0.55), (0.65, 0.6), (1, 0.05)]),
}
LINE, AVG, FILL = "#9CC4FF", "#E3A35E", "#3A73FF"     # the same on every board: the log in chart's colours
SHAPES = {"rise": _RISE, **{kind: _walk(seed, plan) for kind, (seed, plan) in PLANS.items()}}


def _smooth(ys, k=3):
    """A trailing average over k points: the second, calmer line."""
    out = []
    for i in range(len(ys)):
        window = ys[max(0, i - k + 1):i + 1]
        out.append(round(sum(window) / len(window), 1))
    return out


def _path(ys):
    return " ".join(f"{'M' if i == 0 else 'L'}{i * STEP:.1f} {y:.1f}" for i, y in enumerate(ys))


def shape(kind="rise"):
    """What the board's chart needs: the line, the fill under it, the average line, the bars and the colours."""
    ys = SHAPES.get(kind, SHAPES["rise"])
    bars = [(round(i * STEP, 1), round(120 - min(16, 2 + abs(ys[i] - ys[i - 1]) * 0.9), 1)) for i in range(1, N)]
    return {
        "id": kind if kind in SHAPES else "rise",
        "line": _path(ys),
        "fill_path": _path(ys) + " L400 120 L0 120 Z",
        "avg": _path(_smooth(ys)),
        "bars": bars,
        "line_colour": LINE, "avg_colour": AVG, "fill_colour": FILL,
    }
