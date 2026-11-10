// Tap-a-term popups: open the meaning right next to the word that was tapped.
// Without this script the popup still opens (in the middle of the screen); this only moves it closer.
(function () {
  document.documentElement.classList.add("terms-js");
  let openAt = null;                         // scroll position when a popup opened

  function place(button, pop) {
    const r = button.getBoundingClientRect(), gap = 8, pad = 12;
    const w = pop.offsetWidth, h = pop.offsetHeight;
    const left = Math.min(Math.max(pad, r.left), innerWidth - w - pad);
    let top = r.bottom + gap;
    if (top + h > innerHeight - pad) top = Math.max(pad, r.top - gap - h);   // no room below: open above
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  document.querySelectorAll(".term").forEach(button => {
    const pop = document.getElementById(button.getAttribute("popovertarget"));
    if (!pop) return;
    // The browser opens the popup after the click; wait one frame so it has a size, then place it.
    button.addEventListener("click", () => requestAnimationFrame(() => {
      if (pop.matches(":popover-open")) { place(button, pop); openAt = scrollY; }
    }));
  });

  // The popup is fixed to the screen, so close it once the page has scrolled well away from the word.
  addEventListener("scroll", () => {
    if (openAt === null || Math.abs(scrollY - openAt) < 60) return;
    document.querySelectorAll(".term-pop:popover-open").forEach(p => p.hidePopover());
    openAt = null;
  }, { passive: true });
})();
