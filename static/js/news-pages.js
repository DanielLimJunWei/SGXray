// News in pages: a long list of headlines shows 5 at a time, with "Newer" and "Older" buttons and
// "Page 1 of 4" between them. Without this script every headline shows in one list, so nothing is lost.
// Any list with data-per-page="5" gets it; a list that fits on one page gets no buttons at all.
(function () {
  document.querySelectorAll("ul[data-per-page]").forEach(list => {
    if (list.dataset.paged) return;                       // already set up (live.js re-runs this script)
    list.dataset.paged = "1";
    const per = Math.max(1, parseInt(list.dataset.perPage, 10) || 5);
    const items = [...list.children];
    const pages = Math.ceil(items.length / per);
    if (pages <= 1) return;

    const nav = document.createElement("nav");
    nav.className = "news-pager";
    nav.setAttribute("aria-label", "Pages of headlines");
    const newer = document.createElement("button"), older = document.createElement("button");
    const where = document.createElement("span");
    newer.type = older.type = "button";
    newer.className = older.className = "icon-btn compact";
    newer.textContent = "‹ Newer";
    older.textContent = "Older ›";
    where.setAttribute("aria-live", "polite");
    nav.append(newer, where, older);
    list.after(nav);

    let page = 0;
    function show(n, focus) {
      page = Math.max(0, Math.min(pages - 1, n));
      items.forEach((li, i) => { li.hidden = Math.floor(i / per) !== page; });
      where.textContent = `Page ${page + 1} of ${pages}`;
      newer.disabled = page === 0;
      older.disabled = page === pages - 1;
      if (focus) {                                       // keep keyboard users on the list they're reading
        const first = items[page * per].querySelector("summary");
        if (first) first.focus({ preventScroll: true });
        list.scrollIntoView({ block: "nearest", behavior: "auto" });
      }
    }
    newer.addEventListener("click", () => show(page - 1, true));
    older.addEventListener("click", () => show(page + 1, true));
    show(0, false);
  });
})();
