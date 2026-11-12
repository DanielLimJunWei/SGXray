// Per-stock price charts: open from "Price chart" in the holdings table.
// Draws the closing price, your average cost (a dashed step line), your buys (▲) and sells (▼),
// dividend ex-dates (● along the bottom) and bonus issues (a thin dashed line).
// The line draws in once when opened (if animation is on), then stays still.
(function () {
  const sections = [...document.querySelectorAll(".stock-chart")];
  if (!sections.length) return;
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  };
  const H = 260, LEFT = 64, RIGHT = 700, TOP = 34;            // TOP leaves room for the axis title
  const day = iso => new Date(iso + "T00:00:00").getTime();
  const fmt = v => "$" + v.toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const longDate = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "long", year: "numeric" });
  const motionOff = () => document.documentElement.classList.contains("motion-off")
    || matchMedia("(prefers-reduced-motion: reduce)").matches;

  function draw(section) {
    if (section.dataset.drawn) return;
    section.dataset.drawn = "1";
    const D = JSON.parse(section.querySelector(".stock-data").textContent);
    const svg = section.querySelector("svg"), card = svg.closest(".chart-card"), tip = card.querySelector(".chart-tip");
    const idle = () => { tip.textContent = ""; const i = document.createElement("span"); i.className = "idle"; i.textContent = "Point at the chart (or tap it) to see that day's numbers here. Double-click up to 3 days to compare them."; tip.append(i); };
    const P = D.prices, t0 = day(P[0][0]), t1 = day(P[P.length - 1][0]) || t0 + 1;
    const avgs = D.avg_steps.filter(s => s.avg !== null).map(s => s.avg);
    let lo = Math.min(...P.map(p => p[1]), ...avgs), hi = Math.max(...P.map(p => p[1]), ...avgs);
    const pad = (hi - lo) * 0.08 || hi * 0.05; lo -= pad; hi += pad;
    const x = iso => LEFT + (RIGHT - LEFT) * (day(iso) - t0) / (t1 - t0 || 1);
    const y = v => TOP + (H - TOP) * (1 - (v - lo) / (hi - lo));
    const priceOn = iso => { let c = P[0][1]; for (const [d, v] of P) { if (d > iso) break; c = v; } return c; };

    // Axis: 4 price levels and 4 dates.
    const axis = el("g", { class: "axis" });
    for (let k = 0; k <= 3; k++) {
      const v = lo + (hi - lo) * k / 3;
      axis.append(el("line", { x1: LEFT, x2: RIGHT, y1: y(v), y2: y(v) }));
      axis.append(el("text", { x: LEFT - 8, y: y(v) + 4, "text-anchor": "end" }, "$" + v.toFixed(v < 10 ? 2 : 0)));
    }
    [0, 1, 2, 3].forEach(k => {
      const p = P[Math.round(k * (P.length - 1) / 3)];
      axis.append(el("text", { x: x(p[0]), y: H, dy: "1.7em", "text-anchor": "middle" },
        new Date(p[0] + "T00:00:00").toLocaleDateString("en-SG", { month: "short", year: "2-digit" })));
    });
    // Axis titles: what the numbers up the side and along the bottom are.
    axis.append(el("text", { class: "axis-title", x: LEFT - 8, y: TOP - 6, "text-anchor": "end" }, "S$ a share"));
    axis.append(el("text", { class: "axis-title", x: (LEFT + RIGHT) / 2, y: H, dy: "3.2em", "text-anchor": "middle" }, "Date (closing price each trading day)"));
    svg.append(axis);

    // Bonus issues and splits: a thin dashed line on the day the price drops for that reason.
    D.actions.forEach(a => {
      svg.append(el("line", { x1: x(a.date), x2: x(a.date), y1: TOP, y2: H, stroke: "#9AA3B5", "stroke-dasharray": "2 4", "stroke-width": 1 }));
      svg.append(el("text", { class: "chart-note", x: x(a.date) + 4, y: TOP + 10 }, a.factor > 1 ? "bonus issue" : "consolidation"));
    });

    // Your average cost: a step line (flat between trades), drawn dashed.
    let avgPath = "";
    D.avg_steps.forEach((s, i) => {
      if (s.avg === null) return;
      const end = i + 1 < D.avg_steps.length ? D.avg_steps[i + 1].date : P[P.length - 1][0];
      avgPath += `M${x(s.date).toFixed(1)} ${y(s.avg).toFixed(1)} H${x(end).toFixed(1)} `;
    });
    svg.append(el("path", { d: avgPath, fill: "none", stroke: "#E3A35E", "stroke-width": 1.5, "stroke-dasharray": "6 5", opacity: 0.9 }));

    // The price line.
    const line = el("path", { d: P.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join(" "),
      fill: "none", stroke: "#9CC4FF", "stroke-width": 1.75, "stroke-linejoin": "round" });
    svg.append(line);

    // Right-edge labels: today's price and your average cost, pushed apart if they'd overlap.
    const last = P[P.length - 1], avgNow = avgs.length ? D.avg_steps[D.avg_steps.length - 1].avg : null;
    const labels = [{ y: y(last[1]) + 4, text: fmt(last[1]), color: "#9CC4FF" }];
    if (avgNow) labels.push({ y: y(avgNow) + 4, text: "avg " + fmt(avgNow), color: "#E3A35E" });
    labels.sort((a, b) => a.y - b.y).forEach((l, i, all) => { if (i && l.y < all[i - 1].y + 16) l.y = all[i - 1].y + 16; });
    labels.forEach(l => svg.append(el("text", { class: "layer-label", x: RIGHT + 10, y: l.y, fill: l.color }, l.text)));

    // Markers: buys and sells on the line, dividends along the bottom.
    const marks = el("g", { class: "marks" });
    // Buys sit just below the line pointing up, sales just above pointing down, each joined to the exact
    // price by a short stem, so the marker never covers the line itself. Both are solid, with a dark edge.
    D.trades.forEach(t => {
      const cx = x(t.date), cy = y(priceOn(t.date)), up = t.side === "BUY", dir = up ? 1 : -1;
      const tip = cy + dir * 10, base = cy + dir * 22;
      marks.append(el("line", { x1: cx, x2: cx, y1: cy + dir * 3, y2: tip, stroke: up ? "#9CC4FF" : "#F2C1A0", "stroke-width": 1.25 }));
      marks.append(el("polygon", { points: [[cx, tip], [cx - 7, base], [cx + 7, base]].map(p => p.join(",")).join(" "),
        fill: up ? "#9CC4FF" : "#F2C1A0", stroke: "#0A0F1E", "stroke-width": 1.5 }));
    });
    D.dividends.forEach(d => marks.append(el("circle", { cx: x(d.date), cy: H - 6, r: 3.5, fill: "#E3A35E" })));
    // News (w312): a small hollow square along the top on each day a headline mentioned this stock. Point at
    // that day to read the headlines; the dashboard's "In the news" list has the links.
    const newsFrom = P[0][0], newsTo = P[P.length - 1][0];
    [...new Set((D.news || []).map(n => n.date))].filter(d => d >= newsFrom && d <= newsTo).forEach(d =>
      marks.append(el("rect", { class: "news-mark", x: x(d) - 3, y: TOP - 9, width: 6, height: 6, rx: 1 })));
    svg.append(marks);

    // Cursor for reading any day.
    const cursor = el("g", { opacity: 0, "pointer-events": "none" });
    const cl = el("line", { y1: TOP, y2: H, stroke: "#9AA3B5", "stroke-width": 1 }), cd = el("circle", { r: 4, fill: "#9CC4FF", stroke: "#0A0F1E", "stroke-width": 2 });
    cursor.append(cl, cd); svg.append(cursor);

    // Keep chart text about 12px on screen however small the chart is.
    const fit = () => svg.style.setProperty("--svg-text", `${Math.min(26, 12 / (svg.clientWidth / 800 || 1))}px`);
    addEventListener("resize", fit); fit();

    // Draw in once: the line traces left to right, then the markers fade in.
    if (!motionOff()) {
      const len = line.getTotalLength();
      line.style.strokeDasharray = len; line.style.strokeDashoffset = len;
      marks.style.opacity = 0;
      line.getBoundingClientRect();                       // start from the hidden state
      line.style.transition = "stroke-dashoffset 1200ms cubic-bezier(.22,1,.36,1)";
      marks.style.transition = "opacity 400ms ease-out 1000ms";
      requestAnimationFrame(() => { line.style.strokeDashoffset = 0; marks.style.opacity = 1; });
    }

    // Point, tap or use the arrow keys to read a day: its price, and anything you did that day.
    let current = null;
    function show(i) {
      current = Math.max(0, Math.min(P.length - 1, i));
      svg.dataset.cursor = current;
      const [d, v] = P[current], cx = x(d);
      cl.setAttribute("x1", cx); cl.setAttribute("x2", cx); cd.setAttribute("cx", cx); cd.setAttribute("cy", y(v));
      cursor.setAttribute("opacity", 1);
      const prev = current ? P[current - 1][0] : "0000";
      const between = item => item.date > prev && item.date <= d;     // events since the previous point on the line
      const rows = [["Closing price", fmt(v)]];
      const step = D.avg_steps.filter(s => s.date <= d).pop();
      if (step && step.avg !== null) rows.push(["Your average cost", fmt(step.avg)]);
      D.trades.filter(between).forEach(t => rows.push([t.side === "BUY" ? "You bought" : "You sold", `${t.qty.toLocaleString("en-SG")} at ${fmt(t.price)}`]));
      D.dividends.filter(between).forEach(x2 => rows.push(["Dividend", `${x2.shares.toLocaleString("en-SG")} x $${x2.amount} = ${fmt(x2.total)}`]));
      D.actions.filter(between).forEach(a => rows.push([a.factor > 1 ? "Bonus issue" : "Consolidation", "x" + a.factor]));
      (D.news || []).filter(between).slice(0, 3).forEach(n => rows.push(["In the news", `${n.source}: ${n.title}`]));
      tip.textContent = "";
      const head = document.createElement("b"); head.textContent = longDate(d); tip.append(head);
      rows.forEach(([k, val]) => {
        const r = document.createElement("div"), a = document.createElement("span"), b = document.createElement("span");
        a.textContent = k; b.textContent = val; r.append(a, b); tip.append(r);
      });
    }
    const hide = () => { cursor.setAttribute("opacity", 0); idle(); current = null; delete svg.dataset.cursor; };
    const nearest = vx => {                               // the point on the line closest to an x position
      let best = 0, gap = Infinity;
      P.forEach((p, i) => { const g = Math.abs(x(p[0]) - vx); if (g < gap) { gap = g; best = i; } });
      return best;
    };
    svg.addEventListener("pointermove", e => {
      const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse());
      show(nearest(pt.x));
    });
    svg.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") hide(); });
    svg.addEventListener("focus", () => show(current ?? P.length - 1));
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", e => {
      const m = { ArrowLeft: -1, ArrowRight: 1, PageDown: -20, PageUp: 20, Home: -Infinity, End: Infinity }[e.key];
      if (m === undefined) return;
      e.preventDefault();
      show(isFinite(m) ? (current ?? P.length - 1) + m : (m < 0 ? 0 : P.length - 1));
    });

    // Compare up to 3 days: how the price moved between them, and the dividends paid in between.
    const C = window.SGXrayCompare;
    if (C) C({
      svg, panel: card.querySelector(".compare"), count: P.length, title: D.ticker + " price chart", baseY: H,
      xy: i => [x(P[i][0]), y(P[i][1])],
      indexAt: e => nearest(new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse()).x),
      describe: (a, b) => {
        const [da, va] = P[a], [db, vb] = P[b], change = vb - va;
        const paid = D.dividends.filter(d => d.date > da && d.date <= db).reduce((s, d) => s + d.amount, 0);
        const splits = D.actions.filter(x2 => x2.date > da && x2.date <= db);
        const parts = [
          { text: `${C.short(da)} to ${C.short(db)} (${C.days(da, db).toLocaleString("en-SG")} days)` },
          { text: `${fmt(va)} → ${fmt(vb)}` },
          { text: `${C.signed(change)} (${C.pct(change / va)})`, cls: C.trend(change / va) },
        ];
        if (paid) parts.push({ text: `plus $${paid.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")} a share in dividends` });
        if (splits.length) parts.push({ text: "a bonus issue in between lowers the price per share, so this undersells the move", cls: "compare-warn" });
        return parts;
      },
    });
  }

  // Open and close: one stock's chart at a time, right under the holdings table.
  const buttons = [...document.querySelectorAll("[data-chart]")];
  function open(id, from) {
    sections.forEach(s => { s.hidden = s.id !== id; });
    buttons.forEach(b => b.setAttribute("aria-expanded", String(b.dataset.chart === id)));
    const section = document.getElementById(id);
    draw(section);
    section.scrollIntoView({ behavior: motionOff() ? "auto" : "smooth", block: "nearest" });
    section.querySelector("h3").setAttribute("tabindex", "-1");
    section.querySelector("h3").focus({ preventScroll: true });
    section.dataset.opener = from.dataset.chart;
  }
  buttons.forEach(b => {
    b.hidden = false;                                     // only shown when this script runs
    b.addEventListener("click", () => {
      const isOpen = b.getAttribute("aria-expanded") === "true";
      if (isOpen) { document.getElementById(b.dataset.chart).hidden = true; b.setAttribute("aria-expanded", "false"); }
      else open(b.dataset.chart, b);
    });
  });
  sections.forEach(s => s.querySelector("[data-chart-close]").addEventListener("click", () => {
    s.hidden = true;
    const b = buttons.find(x => x.dataset.chart === s.id);
    if (b) { b.setAttribute("aria-expanded", "false"); b.focus(); }
  }));
})();
