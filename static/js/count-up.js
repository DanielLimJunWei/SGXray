// Real numbers count up ONCE when the page opens, then sit still (they're daily closes, not live prices).
// The server already wrote the final text, so without JavaScript, or with "reduce motion" on, nothing changes.
(function () {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const fmt = (x, signed) => {
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
