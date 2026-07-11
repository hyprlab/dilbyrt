/* Dilbyrt front-end behaviour. Vanilla JS, no build step. */
(function () {
  "use strict";
  var root = document.documentElement;

  /* ── theme toggle ─────────────────────────────────────────────────── */
  function setTheme(t) {
    root.setAttribute("data-theme", t);
    try { localStorage.setItem("dilbyrt-theme", t); } catch (e) {}
  }
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    setTheme((root.getAttribute("data-theme") === "dark") ? "light" : "dark");
  });

  /* ── toast auto-dismiss ───────────────────────────────────────────── */
  // Fade + remove flash toasts after a few seconds; click dismisses early.
  // Login-page flashes (error messages) are left to persist.
  (function () {
    var toasts = document.querySelectorAll(".flashes:not(.login-flashes) .flash");
    toasts.forEach(function (el, i) {
      var t;
      function dismiss() {
        clearTimeout(t);
        if (el.classList.contains("flash-out")) return;
        el.classList.add("flash-out");
        setTimeout(function () { el.remove(); }, 240);
      }
      el.addEventListener("click", dismiss);
      t = setTimeout(dismiss, 5000 + i * 400);
    });
  })();

  /* ── mobile sidebar ───────────────────────────────────────────────── */
  var menu = document.getElementById("menu-toggle");
  var side = document.getElementById("sidebar");
  var scrim = document.getElementById("sidebar-scrim");
  function closeSide() { if (side) side.classList.remove("open"); if (scrim) scrim.classList.remove("show"); }
  if (menu && side) {
    menu.addEventListener("click", function (e) {
      e.stopPropagation();
      side.classList.toggle("open");
      if (scrim) scrim.classList.toggle("show", side.classList.contains("open"));
    });
    if (scrim) scrim.addEventListener("click", closeSide);
    side.querySelectorAll("nav a").forEach(function (a) { a.addEventListener("click", closeSide); });
  }

  /* ── modals ───────────────────────────────────────────────────────── */
  function openModal(id) {
    var m = document.getElementById(id);
    if (!m) return;
    m.classList.add("open");
    m.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    var f = m.querySelector("input, select, textarea, button");
    if (f && f.getAttribute("type") !== "hidden") setTimeout(function () { try { f.focus(); } catch (e) {} }, 60);
  }
  function closeModal(m) {
    m.classList.remove("open");
    m.setAttribute("aria-hidden", "true");
    if (!document.querySelector(".modal.open")) document.body.style.overflow = "";
  }
  document.querySelectorAll("[data-open-modal]").forEach(function (el) {
    el.addEventListener("click", function (e) { e.preventDefault(); openModal(el.dataset.openModal); });
  });
  document.querySelectorAll(".modal").forEach(function (m) {
    m.querySelectorAll("[data-close]").forEach(function (el) {
      el.addEventListener("click", function () { closeModal(m); });
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.querySelectorAll(".modal.open").forEach(closeModal);
  });

  /* ── modal tabs (settings popup) ──────────────────────────────────── */
  function activateTab(tabs, name) {
    var modal = tabs.closest(".modal");
    var found = false;
    tabs.querySelectorAll("[data-tab]").forEach(function (b) {
      var on = b.dataset.tab === name;
      b.classList.toggle("active", on);
      if (on) found = true;
    });
    if (!found) return false;
    modal.querySelectorAll("[data-tab-panel]").forEach(function (p) {
      p.hidden = p.dataset.tabPanel !== name;
    });
    return true;
  }
  document.querySelectorAll(".modal-tabs").forEach(function (tabs) {
    tabs.querySelectorAll("[data-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () { activateTab(tabs, btn.dataset.tab); });
    });
  });

  /* Auto-open the settings popup from ?settings=<tab> (used after a save so
     the modal reopens on the right tab), then strip the param so a refresh
     doesn't reopen it. */
  (function () {
    var params = new URLSearchParams(window.location.search);
    var tab = params.get("settings");
    if (!tab) return;
    var modal = document.getElementById("settings-modal");
    if (modal) {
      var tabsEl = modal.querySelector(".modal-tabs");
      if (tabsEl) activateTab(tabsEl, tab);
      openModal("settings-modal");
    }
    params.delete("settings");
    var qs = params.toString();
    try { history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : "")); } catch (e) {}
  })();

  /* ── dropdown menus (export) ──────────────────────────────────────── */
  document.querySelectorAll("[data-menu-toggle]").forEach(function (btn) {
    var pop = btn.parentElement.querySelector(".menu-pop");
    if (!pop) return;
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      pop.hidden = !pop.hidden;
    });
    document.addEventListener("click", function (e) {
      if (!pop.hidden && !pop.contains(e.target) && e.target !== btn) pop.hidden = true;
    });
  });

  /* ── receipts live filter (client-side) ───────────────────────────── */
  var liveFilter = document.querySelector("[data-live-filter]");
  var table = document.getElementById("receipts-table");
  if (liveFilter && table) {
    var noMatch = document.querySelector(".no-match");
    liveFilter.addEventListener("input", function () {
      var q = liveFilter.value.trim().toLowerCase();
      var shown = 0;
      table.querySelectorAll("tbody tr").forEach(function (tr) {
        var hay = tr.getAttribute("data-row-search") || "";
        var match = !q || hay.indexOf(q) !== -1;
        tr.hidden = !match;
        if (match) shown++;
      });
      if (noMatch) noMatch.hidden = shown !== 0;
    });
  }

  /* ── login-background upload label ────────────────────────────────── */
  (function () {
    var input = document.getElementById("login-bg-input");
    var label = document.getElementById("login-bg-label");
    if (!input || !label) return;
    var span = label.querySelector("span");
    input.addEventListener("change", function () {
      var n = input.files ? input.files.length : 0;
      if (span) span.textContent = n ? (n + " image" + (n !== 1 ? "s" : "") + " selected") : "Choose image(s)…";
    });
  })();

  /* ── command palette search ───────────────────────────────────────── */
  (function () {
    var modal = document.getElementById("search-modal");
    if (!modal || !window.DILBYRT_SEARCH_URL) return;
    var input = document.getElementById("search-input");
    var body = document.getElementById("search-modal-body");
    var foot = document.getElementById("search-modal-foot");
    var allLink = document.getElementById("search-modal-all");
    var HINT = '<p class="muted search-modal-hint">Start typing to search your receipts…</p>';
    var timer = null, inflight = null, lastQ = "";

    function open() {
      openModal("search-modal");
      setTimeout(function () { input.focus(); input.select(); }, 70);
    }
    function close() { closeModal(modal); }

    function esc(s) { return (s || "").replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

    function render(data) {
      if (!data.sections || !data.sections.length) {
        body.innerHTML = '<p class="muted search-modal-empty">No matches. Try a different word.</p>';
        foot.hidden = true; return;
      }
      var html = "";
      data.sections.forEach(function (s) {
        html += '<div class="search-section"><div class="search-section-head">' + esc(s.label) + "</div><ul class=\"search-results\">";
        s.items.forEach(function (it) {
          html += '<a class="search-result" href="' + esc(it.url) + '">' +
            '<span class="search-result-text"><span class="search-result-label">' + esc(it.label) +
            '</span><span class="search-result-sub">' + esc(it.snippet) + "</span></span></a>";
        });
        html += "</ul></div>";
      });
      body.innerHTML = html;
      foot.hidden = false;
      if (allLink) allLink.href = window.DILBYRT_SEARCH_PAGE + "?q=" + encodeURIComponent(lastQ);
    }

    function run(q) {
      if (q === lastQ) return; lastQ = q;
      if (q.length < 2) { body.innerHTML = HINT; foot.hidden = true; return; }
      if (inflight) inflight.abort();
      var ctl = new AbortController(); inflight = ctl;
      fetch(window.DILBYRT_SEARCH_URL + "?q=" + encodeURIComponent(q),
        { credentials: "same-origin", signal: ctl.signal, headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.json(); })
        .then(render)
        .catch(function (err) { if (err.name !== "AbortError") body.innerHTML = '<p class="muted search-modal-empty">Search unavailable.</p>'; })
        .finally(function () { if (inflight === ctl) inflight = null; });
    }

    if (input) input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { run(input.value.trim()); }, 140);
    });
    document.querySelectorAll("[data-open-search]").forEach(function (b) {
      b.addEventListener("click", open);
    });
    document.addEventListener("keydown", function (e) {
      var inField = /input|textarea|select/.test((e.target.tagName || "").toLowerCase());
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); open(); }
      else if (e.key === "Enter" && modal.classList.contains("open")) {
        var first = body.querySelector(".search-result");
        if (first) window.location.href = first.getAttribute("href");
      }
    });
  })();

  /* ── receipt form ─────────────────────────────────────────────────── */
  (function () {
    var form = document.querySelector(".receipt-form");
    if (!form) return;

    function money(n) { return "$" + (isFinite(n) ? n : 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    function num(v) { var n = parseFloat((v || "").toString().replace(/[$,]/g, "")); return isFinite(n) ? n : 0; }

    function recalc() {
      var sum = 0;
      form.querySelectorAll(".item-row").forEach(function (row) {
        var q = num(row.querySelector("[data-item-qty]") && row.querySelector("[data-item-qty]").value) || 1;
        var c = num(row.querySelector("[data-item-cost]") && row.querySelector("[data-item-cost]").value);
        var lt = q * c;
        var cell = row.querySelector("[data-line-total]");
        if (cell) cell.textContent = c ? money(lt) : "—";
        sum += lt;
      });
      var out = form.querySelector("[data-items-sum]");
      if (out) out.textContent = money(sum);
      form._itemsSum = sum;
    }

    // Line item add / remove (event-delegated).
    var tpl = document.getElementById("item-row-template");
    var bodyEl = document.getElementById("items-body");
    var addBtn = document.getElementById("add-item");
    if (addBtn && tpl && bodyEl) addBtn.addEventListener("click", function () {
      bodyEl.appendChild(tpl.content.cloneNode(true));
      recalc();
      var rows = bodyEl.querySelectorAll(".item-row");
      var last = rows[rows.length - 1];
      if (last) { var inp = last.querySelector("input"); if (inp) inp.focus(); }
    });
    form.addEventListener("click", function (e) {
      var rm = e.target.closest("[data-remove-item]");
      if (rm) { var row = rm.closest(".item-row"); if (row) { row.remove(); recalc(); } }
    });
    form.addEventListener("input", function (e) {
      if (e.target.matches("[data-item-qty], [data-item-cost]")) recalc();
    });

    var applyBtn = document.getElementById("apply-items-subtotal");
    if (applyBtn) applyBtn.addEventListener("click", function () {
      var sub = form.querySelector("[data-total='subtotal']");
      if (sub) { sub.value = (form._itemsSum || 0).toFixed(2); sub.dispatchEvent(new Event("input", { bubbles: true })); }
    });

    // Subtotal + tax → suggest grand total.
    var subEl = form.querySelector("[data-total='subtotal']");
    var taxEl = form.querySelector("[data-total='tax']");
    var grandEl = form.querySelector("[data-total='grand']");
    var hint = form.querySelector("[data-sum-hint]");
    function checkTotals() {
      if (!subEl || !grandEl || !hint) return;
      var expected = num(subEl.value) + num(taxEl && taxEl.value);
      var grand = num(grandEl.value);
      if (expected > 0 && grand > 0 && Math.abs(expected - grand) > 0.01) {
        hint.hidden = false;
        hint.innerHTML = "Subtotal + tax = " + money(expected) + ", but grand total is " + money(grand) + ". ";
        var a = document.createElement("button");
        a.type = "button"; a.className = "link-btn"; a.textContent = "Use " + money(expected);
        a.addEventListener("click", function () { grandEl.value = expected.toFixed(2); hint.hidden = true; });
        hint.appendChild(a);
      } else { hint.hidden = true; }
    }
    [subEl, taxEl, grandEl].forEach(function (el) { if (el) el.addEventListener("input", checkTotals); });

    // Split mode panels.
    form.querySelectorAll("[data-split-radio]").forEach(function (r) {
      r.addEventListener("change", function () {
        // Drives the panel shown below AND (via CSS on the form) whether the
        // line-items "Bill to" column is visible.
        form.setAttribute("data-split-mode", r.value);
        form.querySelectorAll("[data-split-panel]").forEach(function (p) {
          p.hidden = p.getAttribute("data-split-panel") !== r.value;
        });
      });
    });

    recalc();
    checkTotals();
  })();

  /* ── scan drop label + submit spinner ─────────────────────────────── */
  (function () {
    var drop = document.getElementById("scan-drop");
    var inputEl = document.getElementById("scan-input");
    var scanForm = document.getElementById("scan-form");
    var preview = document.getElementById("scan-preview");
    var previewImg = document.getElementById("scan-preview-img");
    if (drop && inputEl) {
      var textEl = drop.querySelector(".scan-drop-text");
      var defaultText = textEl ? textEl.textContent : "";
      var removeBtn = document.getElementById("scan-remove");
      // Clear the chosen photo so the user can retake / pick another. Emptying
      // the input's value also lets re-selecting the SAME file fire `change`.
      function clearScan() {
        inputEl.value = "";
        if (previewImg) {
          if (previewImg.dataset.url) { try { URL.revokeObjectURL(previewImg.dataset.url); } catch (e) {} }
          previewImg.removeAttribute("src");
          delete previewImg.dataset.url;
        }
        if (preview) preview.hidden = true;
        drop.classList.remove("has-file");
        if (textEl) textEl.textContent = defaultText;
      }
      if (removeBtn) removeBtn.addEventListener("click", clearScan);
      inputEl.addEventListener("change", function () {
        if (inputEl.files && inputEl.files.length) {
          var file = inputEl.files[0];
          drop.classList.add("has-file");
          if (textEl) textEl.textContent = file.name;
          // Show a client-side thumbnail so the user can preview the photo
          // before submitting it to be scanned.
          if (preview && previewImg && file.type.indexOf("image/") === 0) {
            if (previewImg.dataset.url) { try { URL.revokeObjectURL(previewImg.dataset.url); } catch (e) {} }
            var url = URL.createObjectURL(file);
            previewImg.src = url;
            previewImg.dataset.url = url;
            preview.hidden = false;
          }
        }
      });
      ["dragover", "dragenter"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("drag"); });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("drag"); });
      });
      drop.addEventListener("drop", function (e) {
        if (e.dataTransfer && e.dataTransfer.files.length) { inputEl.files = e.dataTransfer.files; inputEl.dispatchEvent(new Event("change")); }
      });
    }
    // ── AJAX scan: POST the photo, show a spinner, and populate the form
    // from the JSON response instead of reloading the page. Falls back to a
    // normal full-page POST when fetch/FormData aren't available.
    var scanUrl = scanForm ? scanForm.getAttribute("data-scan-url") : null;
    var overlay = document.getElementById("scan-loading");
    var status = document.getElementById("scan-status");
    var receiptForm = document.querySelector(".receipt-form");

    function fireInput(el) { if (el) el.dispatchEvent(new Event("input", { bubbles: true })); }
    function setField(name, val) {
      if (!receiptForm) return;
      var el = receiptForm.querySelector('[name="' + name + '"]');
      if (el && val !== undefined && val !== null && val !== "") { el.value = val; fireInput(el); }
    }
    function rebuildItems(items) {
      var tpl = document.getElementById("item-row-template");
      var body = document.getElementById("items-body");
      if (!tpl || !body || !items || !items.length) return;
      body.innerHTML = "";
      items.forEach(function (it) {
        var row = tpl.content.cloneNode(true).querySelector(".item-row");
        var d = row.querySelector('[name="item_desc"]'); if (d) d.value = it.description || "";
        var q = row.querySelector('[name="item_qty"]'); if (q) q.value = (it.qty != null ? it.qty : 1);
        var c = row.querySelector('[name="item_cost"]'); if (c) c.value = (it.cost != null && it.cost !== "" ? it.cost : "");
        body.appendChild(row);
      });
      fireInput(body.querySelector("[data-item-cost]"));   // triggers recalc()
    }
    function populate(data) {
      var f = data.fields || {};
      setField("vendor_name", f.vendor_name);
      setField("purchased_at", f.purchased_at);
      setField("city", f.city);
      setField("state", f.state);
      setField("subtotal", f.subtotal);
      setField("tax", f.tax);
      setField("grand_total", f.grand_total);
      if (receiptForm) {
        var s = receiptForm.querySelector('[name="stored_image"]'); if (s) s.value = data.stored_image || "";
        var o = receiptForm.querySelector('[name="ocr_text"]'); if (o) o.value = data.ocr_text || "";
      }
      rebuildItems(f.items);
      if (status) { status.hidden = false; status.className = "scan-status ok"; status.textContent = data.message || "Scanned — review the fields below."; }
      var details = receiptForm && receiptForm.querySelector(".form-cols");
      if (details && details.scrollIntoView) details.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    if (scanForm) scanForm.addEventListener("submit", function (e) {
      if (!inputEl || !inputEl.files || !inputEl.files.length) {
        e.preventDefault();
        if (drop) { drop.classList.add("drag"); setTimeout(function () { drop.classList.remove("drag"); }, 600); }
        return;
      }
      if (!scanUrl || !window.fetch || !window.FormData) return;   // no-JS fallback
      e.preventDefault();
      var btn = document.getElementById("scan-submit");
      if (overlay) overlay.hidden = false;
      if (status) status.hidden = true;
      if (btn) { btn.classList.add("loading"); btn.disabled = true; var bspan = btn.querySelector("span"); if (bspan) bspan.textContent = "Scanning…"; }

      fetch(scanUrl, { method: "POST", body: new FormData(scanForm), credentials: "same-origin", headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.json().catch(function () { return { ok: false, error: "Couldn't read the scan response." }; }); })
        .then(function (data) {
          if (!data || !data.ok) throw new Error((data && data.error) || "Scan failed. Please try again.");
          populate(data);
        })
        .catch(function (err) {
          if (status) { status.hidden = false; status.className = "scan-status err"; status.textContent = err.message || "Scan failed. Please try again."; }
        })
        .then(function () {   // acts as finally (broad browser support)
          if (overlay) overlay.hidden = true;
          if (btn) { btn.classList.remove("loading"); btn.disabled = false; var bs = btn.querySelector("span"); if (bs) bs.textContent = "Scan & auto-fill"; }
        });
    });
  })();

  /* ── login hero: lightweight floating particles ───────────────────── */
  (function () {
    var canvas = document.querySelector(".login-hero-bg");
    if (!canvas) return;
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var ctx = canvas.getContext("2d");
    var hero = canvas.parentElement, dots = [], raf;
    function size() {
      var r = hero.getBoundingClientRect();
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = r.width * dpr; canvas.height = r.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      dots = [];
      var n = Math.max(18, Math.round(r.width * r.height / 26000));
      for (var i = 0; i < n; i++) dots.push({
        x: Math.random() * r.width, y: Math.random() * r.height,
        r: Math.random() * 2.4 + 0.6, vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25, a: Math.random() * 0.4 + 0.1
      });
    }
    function frame() {
      var r = hero.getBoundingClientRect();
      ctx.clearRect(0, 0, r.width, r.height);
      dots.forEach(function (d) {
        d.x += d.vx; d.y += d.vy;
        if (d.x < 0 || d.x > r.width) d.vx *= -1;
        if (d.y < 0 || d.y > r.height) d.vy *= -1;
        ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255,255,255," + d.a + ")"; ctx.fill();
      });
      raf = requestAnimationFrame(frame);
    }
    size(); frame();
    var t; window.addEventListener("resize", function () { clearTimeout(t); t = setTimeout(size, 200); });
  })();
})();
