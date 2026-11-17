// "See it in the demo" from a lesson: light up the part the lesson is about, bring it into view, and offer
// "Back to the lesson" or "Stay in the demo". Staying clears the highlight and the panel, and tidies the address
// (no ?lesson=), so a refresh is just the demo. The X-ray chart's own extras (the shaded fall, the emphasised
// line) are drawn by xray-chart.js from the same panel's data, and removed here.
(function () {
  const bar = document.querySelector("[data-spot-bar]");
  if (!bar) return;
  const heading = document.getElementById(bar.dataset.spotTarget);
  const part = heading ? (heading.closest("section") || heading) : null;
  if (part) {
    part.classList.add("spotlit");
    part.setAttribute("data-spot-label", "Lesson " + bar.getAttribute("aria-label").replace(/\D+/g, "") + " points here");
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(() => {
      const top = part.getBoundingClientRect().top + scrollY - 140;  // below the top bar, label showing
      scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
    });
  }
  const stay = bar.querySelector("[data-spot-stay]");
  stay.addEventListener("click", e => {
    e.preventDefault();
    if (part) { part.classList.remove("spotlit"); part.removeAttribute("data-spot-label"); }
    document.querySelectorAll(".spot-band, .spot-band-label").forEach(n => n.remove());
    document.querySelectorAll(".spot-line").forEach(n => n.classList.remove("spot-line"));
    bar.hidden = true;
    const url = new URL(location.href);
    url.searchParams.delete("lesson");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  });
})();
