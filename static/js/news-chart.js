// A story card's chart: the stock's last three months, drawn the first time the card opens, with the day of the
// story marked. It comes in with its own quick x-ray: a band of light scans DOWN the film while the line
// "develops" from bright white to its colour (the portfolio's X-ray chart sweeps left to right instead).
// "Animation: on/off" uses the same remembered choice as the X-ray chart ("sgxray-motion" on this device), so
// turned off here it stays off on every other story and page. "Reduce motion" turns it off by default.
(function () {
  const figures = [...document.querySelectorAll("[data-story-chart]")];
  if (!figures.length) return;
  const NS = "http://www.w3.org/2000/svg", KEY = "sgxray-motion";
  const W = 640, H = 200, LEFT = 52, RIGHT = 620, TOP = 16, BOTTOM = 170;
  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  };
  const read = () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } };
  const motionOn = () => {
    const saved = read();
    return saved ? saved === "on" : !matchMedia("(prefers-reduced-motion: reduce)").matches;
  };
  const money = v => "$" + v.toLocaleString("en-SG", { minimumFractionDigits: v < 1 ? 3 : 2, maximumFractionDigits: v < 1 ? 3 : 2 });
  const day = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });

  function draw(fig) {
    if (fig.dataset.drawn) return;
    fig.dataset.drawn = "1";
    const D = JSON.parse(fig.querySelector("script").textContent), P = D.prices;
    const svg = fig.querySelector("svg"), out = fig.querySelector(".story-chart-read");
    if (P.length < 2) { out.textContent = "Not enough saved prices to draw a chart yet."; return; }
    const vals = P.map(p => p[1]), lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo) * 0.1 || hi * 0.02;
    const x = i => LEFT + (RIGHT - LEFT) * i / (P.length - 1);
    const y = v => BOTTOM - (BOTTOM - TOP) * (v - (lo - pad)) / ((hi + pad) - (lo - pad));
    const change = vals[vals.length - 1] / vals[0] - 1, way = change > 0.0005 ? "up" : change < -0.0005 ? "down" : "flat";
    svg.classList.add("chart-" + way);
    const id = "sc" + Math.random().toString(36).slice(2, 8);

    // Axis: the high and low, and the first and last dates.
    [[hi, "high"], [lo, "low"]].forEach(([v]) => {
      svg.append(el("line", { class: "sc-grid", x1: LEFT, x2: RIGHT, y1: y(v), y2: y(v) }));
      svg.append(el("text", { class: "sc-axis", x: LEFT - 6, y: y(v) + 4, "text-anchor": "end" }, money(v)));
    });
    svg.append(el("text", { class: "sc-axis", x: LEFT, y: H - 8 }, day(P[0][0])));
    svg.append(el("text", { class: "sc-axis", x: RIGHT, y: H - 8, "text-anchor": "end" }, day(P[P.length - 1][0])));

    // The line, under a clip that the scan opens from the top down.
    const clip = el("clipPath", { id }), clipRect = el("rect", { x: 0, y: 0, width: W, height: H });
    clip.append(clipRect);
    const defs = el("defs"); defs.append(clip); svg.append(defs);
    const g = el("g", { "clip-path": `url(#${id})` });
    const path = P.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" ");
    g.append(el("path", { class: "sc-area", d: `${path} L${x(P.length - 1)} ${BOTTOM} L${x(0)} ${BOTTOM} Z` }));
    const line = el("path", { class: "sc-line", d: path });
    g.append(line);
    // The story's day: the last close on or before it.
    let si = -1;
    P.forEach((p, i) => { if (p[0] <= D.story_day) si = i; });
    if (si >= 0) {
      g.append(el("line", { class: "sc-story", x1: x(si), x2: x(si), y1: TOP, y2: BOTTOM }));
      g.append(el("circle", { class: "sc-dot", cx: x(si), cy: y(P[si][1]), r: 3.5 }));
      g.append(el("text", { class: "sc-story-label", x: x(si), y: TOP - 4, "text-anchor": si > P.length * 0.8 ? "end" : "middle" }, "this story"));
    }
    svg.append(g);
    const scan = el("rect", { class: "sc-scan", x: 0, y: -14, width: W, height: 14, opacity: 0 });
    svg.append(scan);

    const sum = `${money(vals[0])} → ${money(vals[vals.length - 1])} (${change >= 0 ? "+" : ""}${(change * 100).toFixed(1)}%) over ${P.length} trading days.`;
    const rest = () => { out.textContent = sum + (si >= 0 ? ` On the story's day it closed at ${money(P[si][1])}.` : ""); };
    rest();
    svg.addEventListener("pointermove", e => {
      const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse());
      const i = Math.max(0, Math.min(P.length - 1, Math.round((pt.x - LEFT) / ((RIGHT - LEFT) / (P.length - 1)))));
      out.textContent = `${day(P[i][0])}: closed at ${money(P[i][1])}.`;
    });
    svg.addEventListener("pointerleave", rest);

    // The x-ray: about 0.8 seconds, then still.
    if (motionOn() && !document.documentElement.classList.contains("motion-off")) {
      const start = performance.now(), ms = 800;
      svg.classList.add("developing");
      const step = now => {
        const t = Math.min(1, (now - start) / ms), e = 1 - Math.pow(1 - t, 3), edge = e * H;
        clipRect.setAttribute("height", edge);
        scan.setAttribute("y", edge - 14);
        scan.setAttribute("opacity", t < 1 ? 1 : 0);
        if (t < 1) requestAnimationFrame(step); else svg.classList.remove("developing");
      };
      clipRect.setAttribute("height", 0);
      requestAnimationFrame(step);
    }
  }

  // One switch per card, all showing (and changing) the same remembered choice.
  const switches = figures.map(f => f.querySelector("[data-chart-motion]")).filter(Boolean);
  const show = () => switches.forEach(b => {
    const on = motionOn();
    b.hidden = false;
    b.textContent = "Animation: " + (on ? "on" : "off");
    b.setAttribute("aria-pressed", String(on));
  });
  switches.forEach(b => b.addEventListener("click", e => {
    e.preventDefault();
    const on = !motionOn();
    try { localStorage.setItem(KEY, on ? "on" : "off"); } catch (err) { /* not saved; still works now */ }
    document.documentElement.classList.toggle("motion-off", !on);
    show();
  }));
  show();

  figures.forEach(fig => {
    const card = fig.closest("details");
    if (!card) { draw(fig); return; }
    if (card.open) draw(fig);
    card.addEventListener("toggle", () => { if (card.open) draw(fig); });
  });
})();
