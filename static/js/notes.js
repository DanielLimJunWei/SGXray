// "Why I bought / sold" suggestions. The note box shows an example that fits what you're doing (a company,
// a REIT or an ETF; buying or selling). Press Tab in the EMPTY box to use it, then edit it if you like.
// Once you've typed anything, Tab moves on as normal, so keyboard users are never stuck.
(function () {
  const SUGGEST = {
    stock: "A business I understand, with steady profits; holding for 5+ years",
    reit: "Steady rental income for dividends; holding for 5+ years",
    etf: "The whole market in one buy; adding to it over time",
    sell: "My reason for owning it no longer holds",
  };
  document.querySelectorAll("[data-note-suggest]").forEach(note => {
    const form = note.form;
    if (!form) return;
    const select = form.querySelector("select[name=ticker]");
    const kind = () => {
      const label = select && select.selectedOptions[0] && select.selectedOptions[0].parentElement.label;
      return label === "REITs" ? "reit" : label === "ETFs" ? "etf" : "stock";
    };
    const selling = () => form.querySelector("input[name=side]:checked")?.value === "SELL";
    const update = () => { note.placeholder = selling() ? SUGGEST.sell : SUGGEST[kind()]; };
    form.addEventListener("change", update);
    update();
    note.addEventListener("keydown", e => {
      if (e.key === "Tab" && !e.shiftKey && !note.value.trim()) {
        e.preventDefault();
        note.value = note.placeholder;
        note.setSelectionRange(note.value.length, note.value.length);
      }
    });
  });
})();
