// Learn page progress for people who aren't logged in (w313). Logged in, the server saves finished
// lessons to the account. Logged out, they're remembered in this browser only (localStorage), so
// "3 of 8 read" still works without an account. Nothing here is sent anywhere.
(function () {
  // A link from elsewhere ("Why spreading out helps", a news topic, the self-check) ends in #at-<id>: glide down
  // to that paragraph and let it glow for a moment, so the eye lands on the right sentence. (No element is called
  // "at-...", so the browser itself doesn't jump: the glide is ours. Without this script the lesson opens at the top.)
  const at = location.hash.startsWith("#at-") ? document.getElementById(location.hash.slice(4)) : null;
  if (at) {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    setTimeout(() => {
      const top = at.getBoundingClientRect().top + scrollY - 120;
      scrollTo({ top: Math.max(0, top), behavior: reduce ? "auto" : "smooth" });
      at.classList.add("read-here");
      setTimeout(() => at.classList.remove("read-here"), 4200);
    }, reduce ? 0 : 350);
  }

  const KEY = "sgxray-lessons-read";
  const load = () => {
    try { return new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch (e) { return new Set(); }
  };
  const save = set => {
    try { localStorage.setItem(KEY, JSON.stringify([...set])); } catch (e) { /* private mode: just don't remember */ }
  };

  // "Done · next lesson": remember it here too, then the form carries on to the server as normal.
  document.querySelectorAll("[data-lesson-done]").forEach(form => {
    form.addEventListener("submit", () => {
      const read = load();
      read.add(form.dataset.lessonDone);
      save(read);
    });
  });

  // On the Learn page, when logged out: tick the lessons read in this browser.
  const page = document.querySelector("[data-local-progress]");
  if (!page) return;
  const read = load();
  let count = 0, firstUnread = null;
  page.querySelectorAll("[data-lesson]").forEach(item => {
    const ready = !item.classList.contains("is-soon");
    if (read.has(item.dataset.lesson)) {
      count++;
      item.classList.add("is-read");
      if (ready) item.querySelector(".lesson-state").textContent = "Read";
    } else if (ready && !firstUnread) {
      firstUnread = item;
    }
  });
  page.querySelector("[data-progress-count]").textContent = String(count);
  const start = page.querySelector("[data-start]");
  if (start && count && firstUnread) {
    const link = firstUnread.querySelector("a.lesson-link");
    start.href = link.getAttribute("href");
    start.textContent = "Carry on: " + link.textContent;
  } else if (start && count && !firstUnread) {
    start.hidden = true;                        // every written lesson is read
  }
})();
