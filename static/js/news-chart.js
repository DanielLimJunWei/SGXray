// A story card's chart: the stock's last three months, drawn the first time the card opens, with the day of the
// story marked. Every time the card opens it comes in with its own quick x-ray: a band of light scans DOWN the
// film while the line "develops" from bright white to its colour (the portfolio's X-ray chart sweeps left to
// right instead). "Close chart" hides it in that card ("Show the chart" brings it back, x-ray and all). With
// "reduce motion" on, the chart simply appears.
(function () {
  const figures = [...document.querySelectorAll("[data-story-chart]")];
  if (!figures.length) return;
  const NS = "http://www.w3.org/2000/svg";
  const W = 640, H = 200, LEFT = 52, RIGHT = 620, TOP = 16, BOTTOM = 170;
  const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  };
  const money = v => "$" + v.toLocaleString("en-SG", { minimumFractionDigits: v < 1 ? 3 : 2, maximumFractionDigits: v < 1 ? 3 : 2 });
  const day = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });

  function draw(fig) {
    const D = JSON.parse(fig.querySelector("script").textContent), P = D.prices;
    const svg = fig.querySelector("svg"), out = fig.querySelector(".story-chart-read");
    if (P.length < 2) { out.textContent = "Not enough saved prices to draw a chart yet."; return null; }
    const vals = P.map(p => p[1]), lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo) * 0.1 || hi * 0.02;
    const x = i => LEFT + (RIGHT - LEFT) * i / (P.length - 1);
    const y = v => BOTTOM - (BOTTOM - TOP) * (v - (lo - pad)) / ((hi + pad) - (lo - pad));
    const change = vals[vals.length - 1] / vals[0] - 1, way = change > 0.0005 ? "up" : change < -0.0005 ? "down" : "flat";
    svg.classList.add("chart-" + way);
    const id = "sc" + Math.random().toString(36).slice(2, 8);

    // Axis: the high and low, and the first and last dates.
    [hi, lo].forEach(v => {
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
    g.append(el("path", { class: "sc-line", d: path }));
    let si = -1;                                           // the story's day: the last close on or before it
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
    return { svg, clipRect, scan };
  }

  // The x-ray: about 0.8 seconds, then still. Runs every time the chart is shown.
  function xray(parts) {
    if (!parts) return;
    const { svg, clipRect, scan } = parts;
    cancelAnimationFrame(parts.frame);
    if (reduce()) { clipRect.setAttribute("height", H); scan.setAttribute("opacity", 0); svg.classList.remove("developing"); return; }
    const start = performance.now(), ms = 800;
    svg.classList.add("developing");
    clipRect.setAttribute("height", 0);
    const step = now => {
      const t = Math.min(1, (now - start) / ms), edge = (1 - Math.pow(1 - t, 3)) * H;
      clipRect.setAttribute("height", edge);
      scan.setAttribute("y", edge - 14);
      scan.setAttribute("opacity", t < 1 ? 1 : 0);
      if (t < 1) parts.frame = requestAnimationFrame(step); else svg.classList.remove("developing");
    };
    parts.frame = requestAnimationFrame(step);
  }

  figures.forEach(fig => {
    const card = fig.closest("details");
    const show = card && card.querySelector("[data-chart-show]");
    let parts;
    const open = () => {
      if (fig.hidden) return;
      if (parts === undefined) parts = draw(fig);
      xray(parts);
    };
    fig.querySelector("[data-chart-close]").addEventListener("click", () => {
      fig.hidden = true;
      if (show) { show.hidden = false; show.focus(); }
    });
    if (show) show.addEventListener("click", () => {
      fig.hidden = false;
      show.hidden = true;
      open();
    });
    if (!card) { open(); return; }
    if (card.open) open();
    card.addEventListener("toggle", () => {
      if (!card.open) return;
      fig.hidden = false;                                  // reopening a story shows its chart again
      if (show) show.hidden = true;
      open();
    });
  });
})();
