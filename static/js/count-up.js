// Real numbers count up ONCE when the page opens, then sit still (they're daily closes, not live prices).
// The server already wrote the final text, so without JavaScript, or with "reduce motion" on, nothing changes.
(function () {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  // Rounds like the server (fmt.cents): half a cent goes up, on the number as written (2.675 -> 2.68). The
  // browser's own rounding works on the binary value (2.67499...) and would show 2.67.
  const roundHalfUp = (x, d) => {
    const a = Math.abs(x);
    if (a < 1e-6) return 0;
    const r = Number(Math.round(Number(Number(a.toPrecision(15)) + "e" + d)) + "e-" + d);
    return x < 0 ? -r : r;
  };
  const fmt = (x, signed) => {
    x = roundHalfUp(x, 2);                            // so -0.004 never shows as "-$0.00"
    const sign = x < 0 ? "-" : (signed && x > 0 ? "+" : "");
    return sign + "$" + Math.abs(x).toLocaleString("en-SG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  document.querySelectorAll("[data-count]").forEach(el => {
    const end = parseFloat(el.dataset.count);
    if (!isFinite(end)) return;                       // "n/a" stays as it is
    const finalText = el.textContent, signed = el.hasAttribute("data-signed");
    const arrow = finalText.trim().match(/^[▲▼]/)?.[0];
    const start = performance.now(), ms = 800;
    function step(now) {
      const p = Math.min(1, (now - start) / ms), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = p < 1 ? (arrow ? arrow + " " : "") + fmt(end * eased, signed) : finalText;
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });
})();
