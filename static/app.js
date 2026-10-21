/* NoteNest progressive enhancements. Every feature here is optional:
   the app works fully (add, edit, pin, archive, trash, search) without this file. */
(function () {
  "use strict";
  var root = document.documentElement;

  /* Theme toggle (stored in this browser only). Buttons start hidden and are revealed here. */
  var toggles = document.querySelectorAll("[data-theme-toggle]");
  function effectiveTheme() {
    var set = root.getAttribute("data-theme");
    if (set === "light" || set === "dark") return set;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function syncToggles() {
    var dark = effectiveTheme() === "dark";
    toggles.forEach(function (b) { b.setAttribute("aria-pressed", dark ? "true" : "false"); });
  }
  toggles.forEach(function (b) {
    b.hidden = false;
    b.addEventListener("click", function () {
      var next = effectiveTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("notenest-theme", next); } catch (e) { /* storage unavailable: ignore */ }
      syncToggles();
    });
  });
  syncToggles();

  /* Character counters for textareas. */
  document.querySelectorAll("[data-counter-for]").forEach(function (el) {
    var target = document.getElementById(el.getAttribute("data-counter-for"));
    if (!target) return;
    var max = parseInt(target.getAttribute("maxlength"), 10);
    function update() {
      var n = target.value.length;
      el.textContent = n + " / " + max;
      el.classList.toggle("is-near", n >= max * 0.9);
    }
    el.removeAttribute("aria-hidden");
    target.addEventListener("input", update);
    update();
  });

  /* Dismissible flash messages. */
  document.querySelectorAll(".flash").forEach(function (flash) {
    var close = document.createElement("button");
    close.type = "button";
    close.className = "flash-close";
    close.setAttribute("aria-label", "Dismiss message");
    close.textContent = "\u00d7";
    close.addEventListener("click", function () { flash.remove(); });
    flash.appendChild(close);
  });

  /* Permanent-delete confirmation (Trash page). Forms opt in with data-confirm and may override the
     dialog text with data-confirm-heading / -message / -label. Falls back to window.confirm, or to a
     plain submit if JS fails. Moving a note to Trash is not destructive and needs no confirmation. */
  var dialog = document.getElementById("confirm-dialog");
  var pending = null;
  var headingEl = document.getElementById("confirm-title");
  var confirmBtn = dialog ? dialog.querySelector('button[value="confirm"]') : null;
  var defaultHeading = headingEl ? headingEl.textContent : "";
  var defaultLabel = confirmBtn ? confirmBtn.textContent : "";
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var title = form.getAttribute("data-confirm-title") || "this note";
      var message = form.getAttribute("data-confirm-message") ||
        "\u201c" + title + "\u201d will be permanently deleted. This can\u2019t be undone.";
      if (dialog && typeof dialog.showModal === "function") {
        event.preventDefault();
        pending = form;
        headingEl.textContent = form.getAttribute("data-confirm-heading") || defaultHeading;
        confirmBtn.textContent = form.getAttribute("data-confirm-label") || defaultLabel;
        document.getElementById("confirm-text").textContent = message;
        dialog.returnValue = "";
        dialog.showModal();
      } else if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });
  if (dialog) {
    dialog.addEventListener("close", function () {
      var form = pending;
      pending = null;
      if (form && dialog.returnValue === "confirm") form.submit();
    });
  }

  /* Jump to the composer: focus the title field. */
  function focusComposer() {
    if (location.hash === "#new-note") {
      var t = document.getElementById("new-title");
      if (t) t.focus({ preventScroll: false });
    }
  }
  window.addEventListener("hashchange", focusComposer);
  focusComposer();
})();
