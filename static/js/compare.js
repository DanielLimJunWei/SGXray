// Compare up to 3 points on a chart.
// - Double-click (or double-tap) a day to set a point: A, then B, then C.
// - Click a set point's circle to remove it. "Clear" removes them all.
// - Keyboard: with the chart focused, Enter sets (or removes) a point on the day the cursor is on.
// Each chart says how to read its own points (describe), so the price chart and the X-ray chart
// can show different numbers with the same controls.
window.SGXrayCompare = function ({ svg, panel, count, xy, indexAt, describe, title, baseY }) {
  const NS = "http://www.w3.org/2000/svg", MAX = 3, LETTERS = ["A", "B", "C"];
  const layer = document.createElementNS(NS, "g");
  layer.setAttribute("class", "compare-points");
  svg.append(layer);
  let points = [];                                     // indexes into the chart's data, oldest first

  function render() {
    layer.textContent = "";
    points.forEach((i, n) => {
      const [x, y] = xy(i);
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "compare-point");
      g.setAttribute("tabindex", "0");
      g.setAttribute("role", "button");
      g.setAttribute("aria-label", `Point ${LETTERS[n]}: remove it`);
      const line = document.createElementNS(NS, "line");
      Object.entries({ x1: x, x2: x, y1: y, y2: baseY, stroke: "#9AA3B5", "stroke-dasharray": "2 3" })
        .forEach(([k, v]) => line.setAttribute(k, v));
      const ring = document.createElementNS(NS, "circle");
      Object.entries({ cx: x, cy: y, r: 7, fill: "#0A0F1E", stroke: "#EEE7DC", "stroke-width": 2 }).forEach(([k, v]) => ring.setAttribute(k, v));
      const label = document.createElementNS(NS, "text");
      Object.entries({ x, y: y - 13, "text-anchor": "middle", class: "compare-letter" }).forEach(([k, v]) => label.setAttribute(k, v));
      label.textContent = LETTERS[n];
      g.append(line, ring, label);
      const remove = e => { e.stopPropagation(); points = points.filter(p => p !== i); render(); };
      g.addEventListener("click", remove);
      g.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); remove(e); svg.focus(); } });
      layer.append(g);
    });
    showPanel();
  }

  function showPanel() {
    panel.textContent = "";
    if (!points.length) { panel.hidden = true; return; }
    panel.hidden = false;
    const head = document.createElement("div");
    head.className = "compare-head";
    const h = document.createElement("b");
    h.textContent = points.length === 1 ? `Point A set: double-click another day to compare` : `Comparing ${points.length} points`;
    const clear = document.createElement("button");
    clear.type = "button"; clear.className = "icon-btn compact"; clear.textContent = "Clear";
    clear.addEventListener("click", () => { points = []; render(); svg.focus(); });
    head.append(h, clear);
    panel.append(head);
    const pairs = [];
    for (let n = 1; n < points.length; n++) pairs.push([n - 1, n]);
    if (points.length === 3) pairs.push([0, 2]);
    pairs.forEach(([a, b]) => {
      const row = document.createElement("div");
      row.className = "compare-row";
      const tag = document.createElement("span");
      tag.className = "compare-tag";
      tag.textContent = `${LETTERS[a]} → ${LETTERS[b]}`;
      row.append(tag);
      describe(points[a], points[b]).forEach(part => {
        const s = document.createElement("span");
        if (part.cls) s.className = part.cls;
        s.textContent = part.text;
        row.append(s);
      });
      panel.append(row);
    });
    if (points.length === MAX) {
      const note = document.createElement("p");
      note.className = "compare-note";
      note.textContent = "That's the most: click a point's circle to remove it.";
      panel.append(note);
    }
  }

  function toggle(i) {
    if (i < 0 || i >= count) return;
    if (points.includes(i)) points = points.filter(p => p !== i);
    else if (points.length < MAX) points = [...points, i].sort((a, b) => a - b);
    else { showPanel(); return; }
    render();
  }

  svg.addEventListener("dblclick", e => {
    if (e.target.closest(".compare-point")) return;
    e.preventDefault();
    getSelection()?.removeAllRanges();                 // a double-click shouldn't highlight the axis text
    toggle(indexAt(e));
  });
  svg.addEventListener("keydown", e => {
    if (e.key !== "Enter") return;
    const i = svg.dataset.cursor === undefined ? count - 1 : +svg.dataset.cursor;
    e.preventDefault();
    toggle(i);
  });
  panel.setAttribute("aria-live", "polite");
  panel.setAttribute("aria-label", `Compare points on the ${title}`);
  return { clear: () => { points = []; render(); } };
};

// Small helpers both charts use to word a change.
window.SGXrayCompare.money = v => (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
window.SGXrayCompare.signed = v => (v > 0 ? "+" : v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
window.SGXrayCompare.pct = v => (v > 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
window.SGXrayCompare.trend = v => v > 0.005 ? "up" : v < -0.005 ? "down" : "";
window.SGXrayCompare.days = (a, b) => Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 86400000);
window.SGXrayCompare.short = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
