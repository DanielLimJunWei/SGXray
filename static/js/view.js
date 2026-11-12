// Simple / Detailed (w315). Simple shows the essentials (the key figures, the X-ray, Holdings and Where your
// money is); Detailed adds everything marked data-detail (ups and downs, periods, each stock vs the STI,
// yields, dividends by year, the forecast, sold stocks). The choice is remembered on this device only.
// It starts on Detailed, so nothing disappears until someone chooses. Without JavaScript, everything shows.
(function () {
  const KEY = "sgxray-view";
  const page = () => document.querySelector("[data-live-prices]");
  const read = () => { try { return localStorage.getItem(KEY) === "simple" ? "simple" : "detailed"; } catch (e) { return "detailed"; } };
  function apply(view) {
    const p = page();
    if (!p) return;
    p.classList.toggle("view-simple", view === "simple");
    document.querySelectorAll("[data-view-switch]").forEach(sw => {
      sw.hidden = false;
      sw.querySelectorAll("[data-view]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
    });
  }
  // One listener for the whole page, so it still works after live.js swaps in new prices.
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-view-switch] [data-view]");
    if (!b) return;
    try { localStorage.setItem(KEY, b.dataset.view); } catch (err) { /* private mode: just not remembered */ }
    apply(b.dataset.view);
  });
  // A link straight to a Detailed-only section (like a lesson's "See each stock vs the STI ETF") shows
  // Detailed for this visit, without changing the saved choice, so the link never lands on nothing.
  const wanted = () => {
    const target = location.hash && document.getElementById(location.hash.slice(1));
    return target && target.closest("[data-detail]") ? "detailed" : read();
  };
  apply(wanted());
  addEventListener("hashchange", () => {                             // a link to a section on this same page
    apply(wanted());
    const target = location.hash && document.getElementById(location.hash.slice(1));
    if (target) target.scrollIntoView();
  });
  // live.js replaces the page's content when new prices arrive: put the switch back the way it was.
  new MutationObserver(() => apply(read())).observe(page() || document.body, { childList: true });
})();
