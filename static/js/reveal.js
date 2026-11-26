// Server-drawn charts (like dividends by year) keep their text about 12px on screen, however small the chart is
// shrunk. (Until 26 Nov 2026 this also grew the bars in on first view; the portfolio now shows as it is.)
(function () {
  const fit = () => document.querySelectorAll("svg.bars-chart").forEach(svg => {
    const scale = svg.clientWidth / svg.viewBox.baseVal.width;
    if (scale) svg.style.setProperty("--svg-text", `${Math.min(30, 12 / scale)}px`);
  });
  addEventListener("resize", fit);
  fit();
})();
