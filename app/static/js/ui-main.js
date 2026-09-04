(function () {
  function ensureToastContainer() {
    let container = document.getElementById("appToastStack");
    if (container) {
      return container;
    }

    container = document.createElement("div");
    container.id = "appToastStack";
    container.className = "toast-container position-fixed top-0 end-0 p-3 app-toast-stack";
    document.body.appendChild(container);
    return container;
  }

  function showToast(options) {
    const message = options && options.message ? options.message : "Aksi diproses";
    const title = options && options.title ? options.title : "Notifikasi";
    const variant = options && options.variant ? options.variant : "primary";
    const delay = options && options.delay ? options.delay : 3600;

    if (!window.bootstrap || !window.bootstrap.Toast) {
      return;
    }

    const container = ensureToastContainer();
    const wrapper = document.createElement("div");
    wrapper.className = "toast align-items-center border-0 text-bg-" + variant;
    wrapper.setAttribute("role", "alert");
    wrapper.setAttribute("aria-live", "assertive");
    wrapper.setAttribute("aria-atomic", "true");
    wrapper.innerHTML =
      '<div class="d-flex">' +
      '<div class="toast-body">' +
      '<strong class="d-block mb-1">' + title + '</strong>' +
      '<span>' + message + '</span>' +
      '</div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>' +
      '</div>';

    container.appendChild(wrapper);
    const toast = new window.bootstrap.Toast(wrapper, { delay: delay });
    wrapper.addEventListener("hidden.bs.toast", () => {
      wrapper.remove();
    });
    toast.show();
  }

  function setLoadingState(form) {
    const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!submitButton || submitButton.disabled) {
      return;
    }

    const originalText = submitButton.textContent || submitButton.value || "";
    submitButton.setAttribute("data-original-label", originalText.trim());
    submitButton.disabled = true;
    submitButton.classList.add("is-loading");
    submitButton.setAttribute("aria-busy", "true");

    if (submitButton.tagName.toLowerCase() === "input") {
      submitButton.value = "Memproses...";
    } else {
      submitButton.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>' +
        '<span class="btn-loading-label">Memproses...</span>';
    }
  }

  function showToastFromQueryString() {
    const params = new URLSearchParams(window.location.search);
    const successMessage = params.get("success");
    const errorMessage = params.get("error");
    const infoMessage = params.get("message");

    if (successMessage) {
      showToast({ title: "Berhasil", message: successMessage, variant: "success" });
      return;
    }
    if (errorMessage) {
      showToast({ title: "Gagal", message: errorMessage, variant: "danger" });
      return;
    }
    if (infoMessage) {
      showToast({ title: "Info", message: infoMessage, variant: "primary" });
    }
  }

  function setupSidebarToggle() {
    const toggle = document.getElementById("sidebarToggle");
    const nav = document.getElementById("sidebarNav");
    if (!toggle || !nav) {
      return;
    }

    const mobileQuery = window.matchMedia("(max-width: 992px)");

    function syncDesktopState() {
      if (!mobileQuery.matches) {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
      }
    }

    toggle.addEventListener("click", () => {
      const isOpen = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
    });

    nav.querySelectorAll("a.nav-link").forEach((link) => {
      link.addEventListener("click", () => {
        if (!mobileQuery.matches) {
          return;
        }
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
      });
    });

    if (typeof mobileQuery.addEventListener === "function") {
      mobileQuery.addEventListener("change", syncDesktopState);
    } else if (typeof mobileQuery.addListener === "function") {
      mobileQuery.addListener(syncDesktopState);
    }

    syncDesktopState();
  }

  function setupResponsiveTables() {
    const tables = document.querySelectorAll(".table-responsive table.table");
    tables.forEach((table) => {
      table.classList.add("responsive-stack");
      const headers = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent.trim());
      if (!headers.length) {
        return;
      }

      const rows = table.querySelectorAll("tbody tr");
      rows.forEach((row) => {
        const cells = row.querySelectorAll("td");
        cells.forEach((cell, index) => {
          if (cell.hasAttribute("colspan")) {
            return;
          }
          const label = headers[index] || "Data";
          cell.setAttribute("data-label", label);
        });
      });
    });
  }

  function setupThemeToggle() {
    const root = document.documentElement;
    const toggle = document.getElementById("themeToggle");
    const label = document.getElementById("themeToggleLabel");
    const themes = ["ocean", "slate"];

    function currentTheme() {
      const active = root.getAttribute("data-theme");
      return themes.includes(active) ? active : "ocean";
    }

    function updateLabel(theme) {
      if (!label) {
        return;
      }
      label.textContent = theme === "ocean" ? "Mode Slate" : "Mode Ocean";
    }

    function applyTheme(theme) {
      root.setAttribute("data-theme", theme);
      try {
        localStorage.setItem("appTheme", theme);
      } catch (e) {
        // Ignore storage failures and keep theme applied in-memory.
      }
      updateLabel(theme);
    }

    const initial = currentTheme();
    applyTheme(initial);

    if (!toggle) {
      return;
    }

    toggle.addEventListener("click", () => {
      const next = currentTheme() === "ocean" ? "slate" : "ocean";
      applyTheme(next);
      showToast({
        title: "Tema Aktif",
        message: next === "slate" ? "Mode Slate diaktifkan." : "Mode Ocean diaktifkan.",
        variant: "primary",
        delay: 1800,
      });
    });
  }

  function setupDensityToggle() {
    const root = document.documentElement;
    const toggle = document.getElementById("densityToggle");
    const label = document.getElementById("densityToggleLabel");
    const densities = ["comfort", "compact"];

    function currentDensity() {
      const active = root.getAttribute("data-density");
      return densities.includes(active) ? active : "comfort";
    }

    function updateLabel(value) {
      if (!label) {
        return;
      }
      label.textContent = value === "comfort" ? "Mode Compact" : "Mode Comfort";
    }

    function applyDensity(value) {
      root.setAttribute("data-density", value);
      try {
        localStorage.setItem("appDensity", value);
      } catch (e) {
        // Ignore storage write issues.
      }
      updateLabel(value);
    }

    const initial = currentDensity();
    applyDensity(initial);

    if (!toggle) {
      return;
    }

    toggle.addEventListener("click", () => {
      const next = currentDensity() === "comfort" ? "compact" : "comfort";
      applyDensity(next);
      showToast({
        title: "Kepadatan Tampilan",
        message: next === "compact" ? "Mode Compact diaktifkan." : "Mode Comfort diaktifkan.",
        variant: "primary",
        delay: 1800,
      });
    });
  }

  function setupStaggerMotion() {
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      return;
    }

    const motionTargets = document.querySelectorAll(".motion-target");
    if (!motionTargets.length) {
      return;
    }

    motionTargets.forEach((item, index) => {
      item.classList.add("stagger-item");
      const delay = Math.min(index * 55, 420);
      item.style.setProperty("--stagger-delay", String(delay) + "ms");
    });

    requestAnimationFrame(() => {
      motionTargets.forEach((item) => {
        item.classList.add("is-visible");
      });
    });
  }

  const forms = document.querySelectorAll("form:not([data-no-loading])");
  forms.forEach((form) => {
    form.addEventListener("submit", () => {
      setLoadingState(form);
    });
  });

  window.AppUI = window.AppUI || {};
  window.AppUI.showToast = showToast;

  setupThemeToggle();
  setupDensityToggle();
  setupSidebarToggle();
  setupResponsiveTables();
  setupStaggerMotion();
  showToastFromQueryString();
  setupNotifications();
  setupSidebarCollapse();
  setupTableSearch();
})();

// Notification bell polling — runs outside IIFE so it stays alive
function setupNotifications() {
  const bell = document.getElementById("notifBell");
  const badge = document.getElementById("notifBadge");
  const dropdown = document.getElementById("notifDropdown");
  const list = document.getElementById("notifList");
  const bellWrap = document.getElementById("notifBellWrap");
  const readAllBtn = document.getElementById("notifReadAll");

  if (!bell || !bellWrap) return;
  bellWrap.style.display = "";

  let open = false;

  async function fetchNotifs() {
    try {
      const res = await fetch("/api/notifications");
      if (!res.ok) return;
      const data = await res.json();

      if (data.unread > 0) {
        badge.textContent = data.unread > 99 ? "99+" : data.unread;
        badge.classList.remove("d-none");
      } else {
        badge.classList.add("d-none");
      }

      if (open) renderList(data.items);
    } catch (_) {}
  }

  function renderList(items) {
    if (!items || items.length === 0) {
      list.innerHTML = "<p class='text-muted small text-center py-2'>Tidak ada notifikasi.</p>";
      return;
    }
    list.innerHTML = items.map(function (n) {
      return "<div class='notif-item" + (n.is_read ? "" : " unread") + "' data-id='" + n.id + "'>" +
        "<p class='mb-0'>" + (n.message || "") + "</p>" +
        "<span class='notif-time'>" + (n.created_at || "") + "</span></div>";
    }).join("");

    list.querySelectorAll(".notif-item").forEach(function (el) {
      el.addEventListener("click", function () {
        const id = el.dataset.id;
        if (!el.classList.contains("unread")) return;
        fetch("/api/notifications/" + id + "/read", { method: "POST" }).then(function () {
          el.classList.remove("unread");
          fetchNotifs();
        });
      });
    });
  }

  bell.addEventListener("click", async function (e) {
    e.stopPropagation();
    open = !open;
    dropdown.classList.toggle("d-none", !open);
    if (open) {
      const res = await fetch("/api/notifications");
      if (res.ok) renderList((await res.json()).items);
      fetchNotifs();
    }
  });

  document.addEventListener("click", function () {
    if (open) { open = false; dropdown.classList.add("d-none"); }
  });

  if (readAllBtn) {
    readAllBtn.addEventListener("click", async function (e) {
      e.stopPropagation();
      await fetch("/api/notifications/read-all", { method: "POST" });
      fetchNotifs();
      list.querySelectorAll(".notif-item.unread").forEach(function (el) { el.classList.remove("unread"); });
    });
  }

  fetchNotifs();
  setInterval(fetchNotifs, 90000);
}

function setupSidebarCollapse() {
  var btn = document.getElementById("sidebarCollapseBtn");
  var sidebar = document.getElementById("appSidebar");
  var grid = sidebar && sidebar.closest(".app-grid");
  if (!btn || !sidebar) return;

  var collapsed = false;
  try { collapsed = localStorage.getItem("sidebarCollapsed") === "1"; } catch (e) {}

  function apply(c) {
    collapsed = c;
    sidebar.classList.toggle("is-collapsed", c);
    if (grid) grid.classList.toggle("sidebar-collapsed", c);
    try { localStorage.setItem("sidebarCollapsed", c ? "1" : "0"); } catch (e) {}

    var icon = btn.querySelector("[data-lucide]");
    if (icon) {
      icon.setAttribute("data-lucide", c ? "panel-left-open" : "panel-left-close");
      if (window.lucide) lucide.createIcons({ nodes: [icon] });
    }
  }

  apply(collapsed);
  btn.addEventListener("click", function () { apply(!collapsed); });
}

function setupTableSearch() {
  // Inject a live search box above every panel-card that contains a table
  document.querySelectorAll(".panel-card").forEach(function (card) {
    var table = card.querySelector("table.table");
    if (!table) return;
    var rows = Array.from(table.querySelectorAll("tbody tr"));
    if (rows.length < 4) return; // no point for tiny tables

    var h5 = card.querySelector("h5");
    var wrap = document.createElement("div");
    wrap.className = "page-toolbar";

    var titleClone = document.createElement("span");
    titleClone.className = "fw-bold";
    if (h5) {
      titleClone.textContent = h5.textContent.trim();
      h5.style.display = "none";
    }

    var searchWrap = document.createElement("div");
    searchWrap.className = "table-search-wrap";
    searchWrap.innerHTML =
      '<svg class="table-search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>' +
      '<input type="search" class="form-control table-search-input" placeholder="Cari..." autocomplete="off">';

    wrap.appendChild(titleClone);
    wrap.appendChild(searchWrap);
    if (h5) h5.parentNode.insertBefore(wrap, h5);

    var input = searchWrap.querySelector("input");
    input.addEventListener("input", function () {
      var q = input.value.toLowerCase().trim();
      rows.forEach(function (row) {
        var text = row.textContent.toLowerCase();
        row.style.display = (!q || text.includes(q)) ? "" : "none";
      });
    });
  });
}
