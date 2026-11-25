// The lightbox behind the film: it dims while you type a password (like covering the film, so the
// moment you type something private the screen goes quiet), and brightens as you log in, just before
// the page changes. With "reduce motion" on, it still dims and brightens, just without the fade.
(function () {
  const box = document.querySelector("[data-lightbox]");
  if (!box) return;
  document.querySelectorAll("[data-private]").forEach(field => {
    // The lightbox AND the desk lamp in the corner go down while you type something private.
    field.addEventListener("focus", () => { box.classList.add("dim"); document.documentElement.classList.add("lamp-off"); });
    field.addEventListener("blur", () => { box.classList.remove("dim"); document.documentElement.classList.remove("lamp-off"); });
  });
  // "Show" / "Hide" on every password box, like other sites have, so you can check what you typed.
  // The button is added here (not in the page) so it only appears when it works. Before the form is
  // sent, every box goes back to hidden, so the browser never treats a password as ordinary text.
  document.querySelectorAll('input[type="password"]').forEach(field => {
    const wrap = document.createElement("span");
    wrap.className = "pw-field";
    field.before(wrap);
    wrap.append(field);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pw-toggle";
    btn.textContent = "Show";
    btn.setAttribute("aria-controls", field.id);
    btn.setAttribute("aria-label", "Show password");
    btn.setAttribute("aria-pressed", "false");
    wrap.append(btn);
    const set = shown => {
      field.type = shown ? "text" : "password";
      btn.textContent = shown ? "Hide" : "Show";
      btn.setAttribute("aria-label", shown ? "Hide password" : "Show password");
      btn.setAttribute("aria-pressed", String(shown));
    };
    btn.addEventListener("mousedown", e => e.preventDefault());   // keep the cursor in the box
    btn.addEventListener("click", () => set(field.type === "password"));
    if (field.form) field.form.addEventListener("submit", () => set(false));
  });
  // The self-check's Diagnosis film: both clips are light switches. Click either and the lightbox goes
  // dark, like switching off a real one; click either again and it comes back on. Both clips always show
  // the same state. Just for fun: nothing is saved.
  const switches = [...document.querySelectorAll("[data-light-switch]")];
  switches.forEach(sw => {
    sw.addEventListener("click", () => {
      const off = box.classList.toggle("off");
      switches.forEach(s => {
        s.setAttribute("aria-pressed", String(off));
        s.setAttribute("aria-label", off ? "Turn the lightbox light on" : "Turn the lightbox light off");
        s.title = off ? "Turn the light on" : "Turn the light off";
      });
    });
  });
  // The patient stays "unidentified" while you type: the film only gets your name once you've logged in
  // (the account pages show it then).
  // Too many wrong passwords: count down to when logging in opens again. At 0:00 the form comes back, the
  // note says so, and the lightbox's light flickers back on. The server still decides: trying early is refused.
  const lockNote = document.querySelector("[data-lock-seconds]");
  if (lockNote) {
    const timer = lockNote.querySelector("[data-lock-timer]");
    const fields = document.querySelector("[data-login-fields]");
    const end = Date.now() + parseInt(lockNote.dataset.lockSeconds, 10) * 1000;
    const tick = () => {
      const left = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      timer.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      if (left > 0) return;
      clearInterval(every);
      if (fields) fields.disabled = false;
      lockNote.textContent = "You can try again now.";
      lockNote.classList.add("unlocked");
      lockNote.setAttribute("role", "status");
      box.classList.remove("off", "burst");
      box.classList.add("relight");                    // (no focus jump: the password box would dim it again)
    };
    const every = setInterval(tick, 1000);
    tick();
  }
  const form = document.querySelector("[data-login-form]");
  if (!form) return;
  let sending = false;
  form.addEventListener("submit", e => {
    if (sending || !form.checkValidity()) return;
    e.preventDefault();
    sending = true;
    box.classList.remove("dim");
    document.documentElement.classList.remove("lamp-off");
    box.classList.add("lit");                          // the film lights up: it's yours now
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    setTimeout(() => form.submit(), reduce ? 0 : 380);
  });
})();

// A wrong password turns its box red (login.html); typing again clears the red, since it's a new try.
document.querySelectorAll(".field-wrong").forEach(f => f.addEventListener("input", () => {
  f.classList.remove("field-wrong");
  f.removeAttribute("aria-invalid");
}, { once: true }));
