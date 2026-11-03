/* Indomer HR Portal - page scripts (v9).
 *
 * - Turbo makes links / form submits update the page in place (no full reload).
 * - "ajax regions": search, paging and filters fetch only the table area (#ajax-region) in the background,
 *   so the page never reloads and the search box keeps focus while you type.
 * - Every data table scrolls after 6 rows (sticky header) and has its own search box.
 * Everything is inside init() / initRegion(), which run again for every new page or refreshed region.
 */
(function () {
  "use strict";

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var VISIBLE_ROWS = 6;          // tables scroll after this many rows
  var SEARCH_MIN_ROWS = 4;       // small tables (3 rows or less) do not need a search box
  var clockTimer = null;
  var ajaxSeq = 0, ajaxCtl = null;

  function pad(n) { return String(n).padStart(2, "0"); }
  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function safely(fn, arg) { try { fn(arg); } catch (e) { if (window.console) { console.error(e); } } }
  function submitForm(f) { if (f.requestSubmit) { f.requestSubmit(); } else { f.submit(); } }
  function debounce(fn, ms) {
    var t = null;
    return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); };
  }

  /* ---------- success messages fade away ---------- */
  function initAlerts(root) {
    all(".alert.alert-success", root).forEach(function (el) {
      if (el._fade) { return; }
      el._fade = true;
      setTimeout(function () {
        if (window.bootstrap && document.body.contains(el)) { bootstrap.Alert.getOrCreateInstance(el).close(); }
      }, 4000);
    });
  }

  /* ---------- light / dark theme (icon button, remembered in the browser) ---------- */
  var themeBound = false;
  function initTheme() {
    if (themeBound) { return; }
    themeBound = true;
    document.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest("[data-theme-toggle]");
      if (!btn) { return; }
      var root = document.documentElement;
      var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-bs-theme", next);
      try { localStorage.setItem("hr-theme", next); } catch (err) { /* private mode */ }
      var meta = document.querySelector('meta[name="theme-color"]');
      if (meta) { meta.setAttribute("content", next === "dark" ? "#06223f" : "#0b78b3"); }
    });
  }

  /* ---------- Monthly / Yearly filter: show the month box or the year box, apply by itself ---------- */
  function initPeriodForms(root) {
    all("[data-period-form]", root).forEach(function (form) {
      if (form._pf) { return; }
      form._pf = true;
      var mode = function () {
        var checked = form.querySelector('input[name="period"]:checked');
        return checked ? checked.value : "month";
      };
      var sync = function () {
        var m = mode();
        all("[data-show]", form).forEach(function (el) { el.hidden = el.getAttribute("data-show") !== m; });
      };
      all('input[name="period"]', form).forEach(function (r) {
        r.addEventListener("change", function () { sync(); submitForm(form); });
      });
      // choosing another month / year applies at once - no need to press Apply
      all('input[name="month"], select[name="year"]', form).forEach(function (el) {
        el.addEventListener("change", function () { submitForm(form); });
      });
      sync();
    });
  }

  /* ---------- selects that submit their form when changed ---------- */
  function initAutoSubmit(root) {
    all("select[data-autosubmit]", root).forEach(function (sel) {
      if (sel._as) { return; }
      sel._as = true;
      sel.addEventListener("change", function () { if (sel.form) { submitForm(sel.form); } });
    });
  }

  /* ---------- date pickers: always show 12-Oct-2026 (d-M-Y); the form still submits Y-m-d ---------- */
  var pickerLoading = null;
  function loadPicker(done) {
    if (window.flatpickr) { done(); return; }
    if (!pickerLoading) {
      pickerLoading = [];
      var css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css";
      document.head.appendChild(css);
      var js = document.createElement("script");
      js.src = "https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js";
      js.onload = function () { var q = pickerLoading; pickerLoading = null; q.forEach(function (f) { f(); }); };
      document.head.appendChild(js);
    }
    pickerLoading.push(done);
  }
  function initDates(root) {
    if (!all("input[data-date]", root).length) { return; }
    loadPicker(function () {
      all("input[data-date]", root).forEach(function (el) {
        if (el._flatpickr) { return; }
        flatpickr(el, { altInput: true, altFormat: "d-M-Y", dateFormat: "Y-m-d", allowInput: false, disableMobile: true });
      });
    });
  }

  /* ---------- live clock in the same d-M-Y format ---------- */
  function initClock() {
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
    var clock = document.querySelector("[data-live-clock]");
    if (!clock) { return; }
    var tick = function () {
      var d = new Date();
      var h = d.getHours() % 12 || 12;
      clock.textContent = "Now: " + pad(d.getDate()) + "-" + MONTHS[d.getMonth()] + "-" + d.getFullYear() + " " +
        pad(h) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()) + (d.getHours() >= 12 ? " PM" : " AM");
    };
    tick();
    clockTimer = setInterval(tick, 1000);
  }

  /* ---------- Field work -> ask "On shore / Off shore" ---------- */
  function locScope(modeSel) { return modeSel.closest("tr") || modeSel.closest("form") || document; }
  function syncLocation(modeSel) {
    var type = locScope(modeSel).querySelector("[data-loc-type]");
    if (!type) { return; }
    var show = modeSel.value === "field";
    var holder = type.closest("[data-loc-holder]") || type.closest(".col-md-6") || type;
    holder.hidden = !show;
    type.classList.toggle("needs-choice", show && !type.value && !modeSel.disabled);
    if (!show) { type.value = ""; }
  }
  var locBound = false;
  function initLocation(root) {
    all("[data-loc-mode]", root).forEach(syncLocation);
    if (locBound) { return; }
    locBound = true;
    document.addEventListener("change", function (e) {
      var t = e.target;
      if (t.matches && t.matches("[data-loc-mode]")) { syncLocation(t); }
      else if (t.matches && t.matches("[data-loc-type]")) {
        var m = locScope(t).querySelector("[data-loc-mode]");
        if (m) { syncLocation(m); }
      }
    });
  }

  /* ---------- table search + scroll after 6 rows ---------- */
  function dataRows(body) {
    return all("tr", body).filter(function (tr) { return !tr.hasAttribute("data-no-match") && !tr.querySelector("td[colspan]"); });
  }
  function sizeTable(wrap) {
    var table = wrap.querySelector("table");
    if (!table || !table.tBodies[0]) { return; }
    var rows = dataRows(table.tBodies[0]).filter(function (tr) { return !tr.hidden; });
    if (window.matchMedia("(max-width: 800px)").matches) { wrap.style.maxHeight = ""; wrap.classList.remove("is-scroll"); return; }   // phone: the PAGE scrolls, never a box inside the page
    if (rows.length <= VISIBLE_ROWS) { wrap.style.maxHeight = ""; wrap.classList.remove("is-scroll"); return; }
    if (!table.offsetParent) { return; }                       // hidden tab: measured when it is shown
    var h = rows[VISIBLE_ROWS].getBoundingClientRect().top - table.getBoundingClientRect().top;
    var cap = Math.round(window.innerHeight * 0.72);
    if (window.innerWidth <= 640 && table.classList.contains("stack-table")) { h = Math.min(h, cap); }
    wrap.style.maxHeight = Math.max(Math.round(h), 140) + "px";
    wrap.classList.add("is-scroll");
  }
  function runFilter(input, tables) {
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    tables.forEach(function (table) {
      var body = table && table.tBodies[0];
      if (!body) { return; }
      var shown = 0, real = 0;
      dataRows(body).forEach(function (tr) {
        real++;
        var text = (tr.getAttribute("data-search") || tr.textContent).toLowerCase();
        var ok = words.every(function (w) { return text.indexOf(w) !== -1; });
        tr.hidden = !ok;
        if (ok) { shown++; }
      });
      var showHead = false;                                    // department header rows follow their members
      all("tr", body).reverse().forEach(function (tr) {
        if (tr.classList.contains("dept-row")) { tr.hidden = !showHead && words.length > 0; showHead = false; }
        else if (!tr.hidden && !tr.hasAttribute("data-no-match") && !tr.querySelector("td[colspan]")) { showHead = true; }
      });
      var msg = body.querySelector("tr[data-no-match]");
      if (real && !shown && words.length) {
        if (!msg) {
          msg = document.createElement("tr");
          msg.setAttribute("data-no-match", "");
          msg.className = "empty-row";
          msg.innerHTML = '<td colspan="12" class="text-center text-secondary">Nothing matches your search.</td>';
          body.appendChild(msg);
        }
        msg.hidden = false;
      } else if (msg) {
        msg.hidden = true;
      }
      var wrap = table.closest(".table-responsive");
      if (wrap) { sizeTable(wrap); }
    });
  }
  // page-level search boxes: data-live-filter="table-id table-id" (looked up again each time, tables may be refreshed)
  function initLiveFilter(root) {
    all("input[data-live-filter]", root).forEach(function (input) {
      if (input._lf) { return; }
      input._lf = true;
      var ids = input.getAttribute("data-live-filter").split(/\s+/).filter(Boolean);
      var tables = function () { return ids.map(function (id) { return document.getElementById(id); }).filter(Boolean); };
      input.addEventListener("input", function () { runFilter(input, tables()); });
      runFilter(input, tables());   // the box may already hold a search (e.g. ?q=arun)
    });
  }
  function coveredByPageSearch(table) {
    return !!(table.id && document.querySelector('input[data-live-filter~="' + table.id + '"]'));
  }
  function enhanceTables(root) {
    all("table.fancy-table", root).forEach(function (table) {
      if (table._enh || !table.tBodies[0]) { return; }
      if (table.closest(".member-scroll") || table.hasAttribute("data-no-tools")) { return; }
      table._enh = true;
      var wrap = table.closest(".table-responsive");
      if (!wrap) {
        wrap = document.createElement("div");
        wrap.className = "table-responsive";
        table.parentNode.insertBefore(wrap, table);
        wrap.appendChild(table);
      }
      wrap.classList.remove("history-scroll");
      wrap.classList.add("tscroll");
      if (!coveredByPageSearch(table) && dataRows(table.tBodies[0]).length >= SEARCH_MIN_ROWS) {
        var box = document.createElement("div");
        box.className = "table-search";
        box.innerHTML = '<svg class="ico" width="16" height="16"><use href="#i-search"/></svg>' +
          '<input type="search" class="form-control form-control-sm" placeholder="Search this table..." aria-label="Search this table" autocomplete="off">';
        wrap.parentNode.insertBefore(box, wrap);
        var inp = box.querySelector("input");
        inp.addEventListener("input", function () { runFilter(inp, [table]); });
        inp.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); } });
      }
      sizeTable(wrap);
    });
  }
  function resizeTables() { all(".table-responsive.tscroll").forEach(sizeTable); }

  /* ---------- project / group form: search / select the members ---------- */
  // frozen header: tell the CSS how tall it is so the page content starts right below it
  function syncHeaderSpace() {
    var h = document.querySelector(".app-header");
    if (!h) { return; }
    var top = parseFloat(getComputedStyle(h).top) || 0;
    document.documentElement.style.setProperty("--hdr-space", Math.ceil(h.offsetHeight + top + 10) + "px");
    if (window.ResizeObserver && !h._ro) {
      h._ro = new ResizeObserver(syncHeaderSpace);
      h._ro.observe(h);
    }
  }
  window.addEventListener("resize", syncHeaderSpace);

  // ---- Permissions page: Create / Edit tick View, un-ticking View clears Create / Edit, column + row shortcuts
  document.addEventListener("change", function (ev) {
    var box = ev.target;
    if (!box || box.type !== "checkbox") { return; }
    var form = box.closest("[data-perm-form]");
    if (!form) { return; }
    var colField = box.getAttribute("data-perm-col");
    if (colField) {                                   // header box: whole column (only rows that are shown)
      all('input[data-perm="' + colField + '"]', form).forEach(function (c) {
        if (!c.closest("tr").hidden) { c.checked = box.checked; syncPerm(c); }
      });
      return;
    }
    if (box.hasAttribute("data-perm")) { syncPerm(box); }
  });
  function syncPerm(box) {
    var row = box.closest("tr"), f = box.getAttribute("data-perm") || "";
    var m = f.match(/^can_(create|edit|view)_(employees|projects)$/);
    if (!m || !row) { return; }
    var view = row.querySelector('input[data-perm="can_view_' + m[2] + '"]');
    if (m[1] !== "view" && box.checked && view) { view.checked = true; }
    if (m[1] === "view" && !box.checked) {
      ["create", "edit"].forEach(function (a) {
        var o = row.querySelector('input[data-perm="can_' + a + '_' + m[2] + '"]');
        if (o) { o.checked = false; }
      });
    }
  }
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest ? ev.target.closest("[data-perm-row]") : null;
    if (!btn) { return; }
    var on = btn.getAttribute("data-perm-row") === "all";
    all("input[data-perm]", btn.closest("tr")).forEach(function (c) { c.checked = on; });
  });
  document.addEventListener("turbo:load", syncHeaderSpace);
  document.addEventListener("DOMContentLoaded", syncHeaderSpace);

  // Employee table: tick several rows -> "Delete selected (n)" with one confirmation
  function initBulkSelect(root) {
    var form = document.querySelector("[data-bulk-form]");
    if (!form) { return; }
    var btn = form.querySelector("[data-bulk-btn]"), count = form.querySelector("[data-bulk-count]");
    var checks = function () { return all("[data-row-check]:not(:disabled)", document); };
    var refresh = function () {
      var n = checks().filter(function (c) { return c.checked; }).length;
      count.textContent = n;
      btn.hidden = n === 0;
      all("[data-select-all]", document).forEach(function (a) { a.checked = n > 0 && n === checks().length; });
    };
    all("[data-select-all]", root).forEach(function (a) {
      if (a._bs) { return; }
      a._bs = true;
      a.addEventListener("change", function () { checks().forEach(function (c) { c.checked = a.checked; }); refresh(); });
    });
    all("[data-row-check]", root).forEach(function (c) {
      if (c._bs) { return; }
      c._bs = true;
      c.addEventListener("change", refresh);
    });
    if (!form._bs) {
      form._bs = true;
      form.addEventListener("submit", function (ev) {
        var n = parseInt(count.textContent, 10) || 0;
        if (!n || !window.confirm("Delete " + n + " selected employee(s) and their logins? This cannot be undone.")) { ev.preventDefault(); }
      });
    }
    refresh();
  }

  // profile photo: pick a picture, shrink it to 256 x 256 (centre crop) in the browser, then upload
  function initPhotoUpload(root) {
    all("[data-photo-input]", root).forEach(function (input) {
      if (input._ph) { return; }
      input._ph = true;
      input.addEventListener("change", function () {
        var f = input.files && input.files[0];
        if (!f) { return; }
        if (!/^image\//.test(f.type)) { alert("Please choose a picture (JPG, PNG or WEBP)."); return; }
        var img = new Image(), url = URL.createObjectURL(f);
        img.onload = function () {
          var size = 256, c = document.createElement("canvas");
          c.width = c.height = size;
          var s = Math.min(img.width, img.height);
          c.getContext("2d").drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, size, size);
          var form = input.closest("form");
          form.querySelector("[name=photo_data]").value = c.toDataURL("image/jpeg", 0.85);
          URL.revokeObjectURL(url);
          if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
        };
        img.onerror = function () { alert("This picture could not be read."); };
        img.src = url;
      });
    });
  }

  // textareas with data-word-limit="100": live "12 / 100 words" counter, extra words are cut off
  function initWordLimit(root) {
    all("textarea[data-word-limit], input[data-word-limit]", root).forEach(function (el) {
      if (el._wl) { return; }
      el._wl = true;
      var limit = parseInt(el.getAttribute("data-word-limit"), 10) || 100;
      var note = document.createElement("div");
      note.className = "word-count";
      el.parentNode.insertBefore(note, el.nextSibling);
      var update = function () {
        var words = (el.value.match(/\S+/g) || []).length;
        if (words > limit) {
          var m = el.value.match(new RegExp("^\\s*(?:\\S+\\s+){" + (limit - 1) + "}\\S+"));
          if (m) { el.value = m[0]; words = limit; }
        }
        note.textContent = words + " / " + limit + " words";
        note.classList.toggle("over", words >= limit);
      };
      el.addEventListener("input", update);
      update();
    });
  }

  function initMemberPicker(root) {
    all("[data-member-picker]", root).forEach(function (box) {
      if (box._mp) { return; }
      box._mp = true;
      var search = box.querySelector("[data-member-search]");
      var rows = all("[data-member-row]", box);
      var counter = box.querySelector("[data-member-count]");
      var onlyBtn = box.querySelector("[data-member-only]");
      var allBtn = box.querySelector("[data-member-all]");
      var clearBtn = box.querySelector("[data-member-clear]");
      var empty = box.querySelector("[data-member-empty]");
      var onlySelected = false;

      var box_ = function (row) { return row.querySelector('input[type="checkbox"]'); };
      var isOn = function (row) { var c = box_(row); return !!(c && c.checked); };

      var refresh = function () {
        var words = (search ? search.value : "").toLowerCase().split(/\s+/).filter(Boolean);
        var shown = 0;
        rows.forEach(function (row) {
          var text = (row.getAttribute("data-search") || row.textContent).toLowerCase();
          var ok = words.every(function (w) { return text.indexOf(w) !== -1; });
          var on = isOn(row);
          if (onlySelected && !on) { ok = false; }
          row.hidden = !ok;
          if (ok) { shown++; }
          row.classList.toggle("member-on", on);
          var sel = row.querySelector("select");
          // a ticked member must get Office or Field - highlight the box until it is chosen
          if (sel) { sel.classList.toggle("needs-choice", on && !sel.value); }
        });
        var picked = rows.filter(isOn).length;
        if (counter) { counter.textContent = picked + " selected"; }
        if (empty) { empty.hidden = shown !== 0; }
        if (onlyBtn) { onlyBtn.classList.toggle("active", onlySelected); }
      };

      box.addEventListener("change", refresh);
      if (search) {
        search.addEventListener("input", refresh);
        // pressing Enter in the search box must not submit the whole form
        search.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); } });
      }
      var deptSel = box.querySelector("[data-dept-pick]");
      if (deptSel) {
        deptSel.addEventListener("change", function () {
          if (!deptSel.value) { return; }
          rows.forEach(function (row) {
            var c = box_(row);
            if (c && row.getAttribute("data-dept") === deptSel.value) { c.checked = true; }
          });
          deptSel.value = "";
          refresh();
        });
      }
      if (onlyBtn) { onlyBtn.addEventListener("click", function () { onlySelected = !onlySelected; refresh(); }); }
      if (allBtn) {
        allBtn.addEventListener("click", function () {
          rows.forEach(function (row) {
            var c = box_(row);
            if (c && !row.hidden) { c.checked = true; }
          });
          refresh();
        });
      }
      if (clearBtn) {
        clearBtn.addEventListener("click", function () {
          rows.forEach(function (row) { var c = box_(row); if (c) { c.checked = false; } });
          onlySelected = false;
          refresh();
        });
      }
      refresh();
    });
  }

  /* ---------- WhatsApp: computer -> WhatsApp Web, phone -> WhatsApp app (wa.me) ---------- */
  function waNumber(raw) {
    var d = String(raw || "").replace(/\D/g, "");
    if (d.length === 10) { d = "91" + d; } else if (d.length === 11 && d.charAt(0) === "0") { d = "91" + d.slice(1); }
    return d;
  }
  function initWhatsApp(root) {
    var mobile = /Android|iPhone|iPad|iPod|Mobile|Opera Mini|IEMobile/i.test(navigator.userAgent || "");
    all("a[data-wa]", root).forEach(function (a) {
      var num = waNumber(a.getAttribute("data-wa-phone")), text = encodeURIComponent(a.getAttribute("data-wa-text") || "");
      if (!num) { return; }
      a.href = mobile ? "https://wa.me/" + num + "?text=" + text
                      : "https://web.whatsapp.com/send?phone=" + num + "&text=" + text;
    });
    // "Open next chat": opens the first member not opened yet (one click = one chat, so browsers do not block it)
    all("[data-wa-next]", root).forEach(function (btn) {
      if (btn._wa) { return; }
      btn._wa = true;
      btn.addEventListener("click", function () {
        var rows = all("[data-wa-row]", btn.closest("[data-wa-list]") || document);
        var next = rows.filter(function (r) { return !r.hasAttribute("data-wa-opened") && r.querySelector("a[data-wa]"); })[0];
        if (!next) { btn.textContent = "All opened"; btn.disabled = true; return; }
        next.setAttribute("data-wa-opened", "1");
        next.classList.add("row-muted");
        window.open(next.querySelector("a[data-wa]").href, "_blank", "noopener");
      });
    });
  }

  /* ---------- password: Show / Hide ---------- */
  function initReveal(root) {
    all("[data-reveal]", root).forEach(function (btn) {
      if (btn._rv) { return; }
      btn._rv = true;
      btn.addEventListener("click", function () {
        var box = btn.parentNode.querySelector("[data-secret-text]");
        if (!box) { return; }
        var hidden = box.getAttribute("data-secret-hidden") === "true";
        box.textContent = hidden ? box.getAttribute("data-secret-text") : "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022";
        box.setAttribute("data-secret-hidden", hidden ? "false" : "true");
        btn.textContent = hidden ? "Hide" : "Show";
      });
    });
  }

  /* ---------- chat: keep the newest message in view ---------- */
  function initChat(root) {
    all("[data-chat-scroll]", root).forEach(function (box) { box.scrollTop = box.scrollHeight; });
    all("textarea[data-chat-input]", root).forEach(function (ta) {
      if (ta._ci) { return; }
      ta._ci = true;
      var fit = function () { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 120) + "px"; };
      ta.addEventListener("input", fit);
      // Enter sends, Shift+Enter makes a new line
      ta.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          if (ta.form && ta.value.trim()) { submitForm(ta.form); }
        }
      });
    });
  }

  /* ================= AJAX: refresh only #ajax-region ================= */
  function bar() {
    var b = document.getElementById("ajax-bar");
    if (!b) { b = document.createElement("div"); b.id = "ajax-bar"; b.className = "ajax-bar"; document.body.appendChild(b); }
    return b;
  }
  function flash(html) {
    var f = document.getElementById("flash");
    if (!f || !html) { return; }
    f.innerHTML = html;
    initAlerts(f);
  }
  function applyFragment(html, url, push) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var fresh = doc.getElementById("ajax-region");
    var region = document.getElementById("ajax-region");
    if (!fresh || !region) { return false; }
    region.innerHTML = fresh.innerHTML;
    all("[data-ajax-sync]").forEach(function (el) {
      var src = el.id && doc.getElementById(el.id);
      if (src) { el.innerHTML = src.innerHTML; }
    });
    var fl = doc.getElementById("ajax-flash");
    if (fl) { flash(fl.innerHTML); }
    if (url && push) {
      try { history.replaceState(history.state, "", url); } catch (e) { /* ignore */ }
    }
    initRegion(region);
    return true;
  }
  function ajaxLoad(url, opts) {
    opts = opts || {};
    var region = document.getElementById("ajax-region");
    if (!region || !window.fetch) { location.href = url; return; }
    if (ajaxCtl && ajaxCtl.abort) { ajaxCtl.abort(); }
    ajaxCtl = window.AbortController ? new AbortController() : null;
    var seq = ++ajaxSeq;
    region.classList.add("is-loading");
    var b0 = bar(); b0.className = "ajax-bar"; void b0.offsetWidth; b0.className = "ajax-bar run";
    var init = { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } };
    if (opts.method === "POST") { init.method = "POST"; init.body = opts.body; }
    if (ajaxCtl) { init.signal = ajaxCtl.signal; }
    fetch(url, init).then(function (r) {
      if (r.redirected && /\/(admin-)?login\//.test(r.url)) { location.href = url; return null; }   // session ended
      return r.text().then(function (t) { return { ok: r.ok, status: r.status, text: t, url: r.url }; });
    }).then(function (res) {
      if (!res || seq !== ajaxSeq) { return; }
      var shown = res.ok && applyFragment(res.text, opts.method === "POST" ? null : url, true);
      if (!shown) { location.href = opts.method === "POST" ? location.href : url; return; }
      if (opts.done) { opts.done(); }
    }).catch(function (err) {
      if (err && err.name === "AbortError") { return; }
      location.href = opts.method === "POST" ? location.href : url;      // network trouble: do it the normal way
    }).then(function () {
      if (seq === ajaxSeq) { region.classList.remove("is-loading"); bar().className = "ajax-bar done"; }
    });
  }
  // build the new URL: keep what is already in the address, change only what this form controls
  function formUrl(form) {
    var u = new URL(location.href);
    var p = u.searchParams;
    all("input, select, textarea", form).forEach(function (el) {
      if (!el.name || el.type === "hidden" || el.type === "submit" || el.disabled) { return; }
      if ((el.type === "radio" || el.type === "checkbox") && !el.checked) { return; }
      if (el.value === "") { p.delete(el.name); } else { p.set(el.name, el.value); }
    });
    Array.from(p.keys()).forEach(function (k) { if (/page$/i.test(k)) { p.delete(k); } });
    var qs = p.toString();
    return u.pathname + (qs ? "?" + qs : "");
  }
  var ajaxBound = false;
  function initAjax() {
    if (ajaxBound) { return; }
    ajaxBound = true;
    document.addEventListener("click", function (e) {
      if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
      var a = e.target.closest && e.target.closest("a[data-ajax]");
      if (!a || !document.getElementById("ajax-region")) { return; }
      e.preventDefault();
      ajaxLoad(a.getAttribute("href"));
    });
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (e.defaultPrevented || !form.matches || !document.getElementById("ajax-region")) { return; }
      if (form.hasAttribute("data-ajax") && (form.method || "get").toLowerCase() === "get") {
        e.preventDefault();
        ajaxLoad(formUrl(form));
      } else if (form.hasAttribute("data-ajax-post")) {              // e.g. sending a chat message
        e.preventDefault();
        var field = form.querySelector("textarea, input[type=text]");
        ajaxLoad(form.getAttribute("action") || location.pathname + location.search, {
          method: "POST", body: new FormData(form),
          done: function () { if (field) { field.value = ""; field.style.height = ""; field.focus(); } }
        });
      }
    });
    // typing in a page search box: instant filter of what is shown (initLiveFilter) + the real search after a short pause
    document.addEventListener("input", debounce(function (e) {
      var input = e.target;
      if (!input.matches || !input.matches("input[data-ajax-search]") || !input.form) { return; }
      if (!document.getElementById("ajax-region")) { return; }
      var url = formUrl(input.form);
      if (url !== location.pathname + location.search) { ajaxLoad(url); }
    }, 350));
  }

  /* keeps pager / filter links on the ajax path (no Turbo visit) */
  function markAjaxLinks(root) {
    all(".pager a, a[data-turbo-action='replace']", root).forEach(function (a) { a.setAttribute("data-ajax", ""); });
  }

  /* ---------- everything inside a page / refreshed region ---------- */
  function initRegion(root) {
    root = root || document;
    safely(markAjaxLinks, root);
    safely(initAlerts, root);
    safely(initPeriodForms, root);
    safely(initAutoSubmit, root);
    safely(initDates, root);
    safely(initLocation, root);
    safely(initLiveFilter, root);
    safely(initMemberPicker, root);
    safely(initWordLimit, root);
    safely(initPhotoUpload, root);
    safely(initBulkSelect, root);
    safely(initWhatsApp, root);
    safely(initReveal, root);
    safely(initChat, root);
    safely(enhanceTables, root);
  }

  function init() {
    if (document.body.dataset.portalReady) { return; }   // the <body> is replaced on every Turbo visit
    document.body.dataset.portalReady = "1";
    safely(initTheme);
    safely(initAjax);
    safely(initClock);
    initRegion(document);
    // login / logout: forget the pages Turbo kept for the Back button (nobody sees the old user's pages)
    all("form[data-clear-cache]").forEach(function (f) {
      f.addEventListener("submit", function () { if (window.Turbo && Turbo.cache) { Turbo.cache.clear(); } });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  var progressSet = false;
  document.addEventListener("turbo:load", function () {
    if (!progressSet && window.Turbo && Turbo.setProgressBarDelay) { Turbo.setProgressBarDelay(100); progressSet = true; }
    init();
  });
  document.addEventListener("turbo:submit-start", function (e) {
    if (e.target && e.target.classList) { e.target.classList.add("is-busy"); }
  });
  document.addEventListener("turbo:submit-end", function (e) {
    if (e.target && e.target.classList) { e.target.classList.remove("is-busy"); }
  });
  // a tab / accordion that was hidden is measured when it is shown
  document.addEventListener("shown.bs.tab", resizeTables);
  window.addEventListener("resize", debounce(resizeTables, 200));
  // what Turbo keeps for the Back button must be clean: no date-picker copies, no old messages, no search boxes we added
  document.addEventListener("turbo:before-cache", function () {
    all("input[data-date]").forEach(function (el) { if (el._flatpickr) { el._flatpickr.destroy(); } });
    all(".alert").forEach(function (el) { el.remove(); });
    all("[data-no-match]").forEach(function (el) { el.remove(); });
    all("tr[hidden]").forEach(function (el) { el.hidden = false; });
    all(".table-search").forEach(function (el) { el.remove(); });
    all(".table-responsive.tscroll").forEach(function (el) { el.style.maxHeight = ""; el.classList.remove("tscroll", "is-scroll"); });
    all("table.fancy-table").forEach(function (t) { t._enh = false; });
    all("#ajax-region.is-loading").forEach(function (el) { el.classList.remove("is-loading"); });
    var b = document.getElementById("ajax-bar"); if (b) { b.remove(); }
    delete document.body.dataset.portalReady;
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null; }
  });
})();

/* v14: "+" button on the employee form -> second emergency contact (works with Turbo page changes, bound once) */
(function () {
  if (window.__contact2Bound) { return; }
  window.__contact2Bound = true;
  document.addEventListener("click", function (e) {
    var add = e.target.closest && e.target.closest("[data-add-contact]");
    if (add) {
      var box = document.getElementById("contact2-box");
      if (box) { box.hidden = false; add.hidden = true; var first = box.querySelector("input"); if (first) { first.focus(); } }
      return;
    }
    var rm = e.target.closest && e.target.closest("[data-remove-contact]");
    if (rm) {
      var b = document.getElementById("contact2-box");
      if (b) {
        b.querySelectorAll("input").forEach(function (i) { i.value = ""; });
        b.querySelectorAll(".text-danger").forEach(function (i) { i.remove(); });
        b.hidden = true;
      }
      var plus = document.querySelector("[data-add-contact]");
      if (plus) { plus.hidden = false; }
    }
  });
})();

/* v16: "+ Add doctor" button on the employee form -> shows Doctor 2, then Doctor 3 (bound once, works with Turbo) */
(function () {
  if (window.__doctorBound) { return; }
  window.__doctorBound = true;
  function refreshPlus() {
    var plus = document.querySelector("[data-add-doctor]");
    if (!plus) { return; }
    var hiddenBoxes = document.querySelectorAll("[data-doctor-box][hidden]");
    plus.hidden = hiddenBoxes.length === 0;
  }
  document.addEventListener("click", function (e) {
    var add = e.target.closest && e.target.closest("[data-add-doctor]");
    if (add) {
      var next = document.querySelector("[data-doctor-box][hidden]");
      if (next) { next.hidden = false; var i = next.querySelector("input"); if (i) { i.focus(); } }
      refreshPlus();
      return;
    }
    var rm = e.target.closest && e.target.closest("[data-remove-doctor]");
    if (rm) {
      var box = rm.closest("[data-doctor-box]");
      if (box) {
        box.querySelectorAll("input").forEach(function (i) { i.value = ""; });
        box.querySelectorAll(".text-danger").forEach(function (i) { i.remove(); });
        box.hidden = true;
      }
      refreshPlus();
    }
  });
})();
