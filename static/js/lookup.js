// "Can't find your stock in the list?": look the code up without reloading the page.
// If the code isn't found, the message appears right under the box, where you're looking.
// If it is found, go on to the trades page with the stock picked (the server's redirect).
// Without this script the form still works: it posts normally and the page lands back on #lookup.
(function () {
  const form = document.querySelector(".lookup-form");
  if (!form) return;
  const button = form.querySelector("button[type=submit]");
  const input = form.querySelector("#lookup-code");

  function showError(text) {
    let box = form.querySelector(".form-error");
    if (!box) {
      box = document.createElement("p");
      box.className = "form-error";
      box.setAttribute("role", "alert");
      form.appendChild(box);
    }
    box.textContent = text;            // textContent, never innerHTML: the message is shown as plain text
    input.focus();
    input.select();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    const label = button.textContent;
    button.textContent = "Looking it up…";
    try {
      const response = await fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" });
      if (response.redirected) {                       // found (or already listed): show it picked in the form
        window.location.assign(response.url);
        return;
      }
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const message = page.querySelector(".lookup .form-error, .auth-card .muted");   // our message, or an error page's
      showError(message ? message.textContent.trim() : "Something went wrong. Try again in a moment.");
    } catch (e) {
      showError("SGXray couldn't be reached. Check your connection and try again.");
    }
    button.disabled = false;
    button.textContent = label;
  });
})();
