"""
Shared admin top navigation (matches Upload page header: brand, tagline, links, Merchant pill, theme, log out).
"""
from __future__ import annotations


def admin_top_nav_html(active: str = "writter", *, show_admin_links: bool = True) -> str:
    """Full-width sticky header. `active` is one of: upload, dashboard, writter, settings."""

    def _cls(name: str) -> str:
        return "nav-link active" if active == name else "nav-link"

    admin_block = ""
    if show_admin_links:
        admin_block = f"""
    <a href="/admin/onboarding-analytics" class="{_cls('dashboard')}">Dashboard</a>
    <a href="/admin/writter" class="{_cls('writter')}">Writter</a>
    <a href="/settings" class="{_cls('settings')}">Settings</a>"""

    return f"""<nav class="nav" aria-label="Main">
  <a href="/" class="nav-brand">
    <span class="nav-brand-imgwrap">
      <img class="logo-light nav-logo-img" src="/assets/logo-light.png" alt="Cartozo.ai" />
      <img class="logo-dark nav-logo-img" src="/assets/logo-dark.png" alt="Cartozo.ai" />
    </span>
  </a>
  <div class="nav-links">
    <a href="/batches/history" class="nav-link">Batch history</a>
    <a href="/upload" class="{_cls('upload')}">Upload</a>{admin_block}
    <div class="nav-merchant" id="navMerchantWrap">
      <a href="/merchant/google/connect" class="nav-merchant-connect" id="merchantConnectBtn">Connect Merchant Center</a>
      <div class="nav-merchant-connected" id="navMerchantConnected">
        <button type="button" class="nav-merchant-pill" id="merchantConnectedLabel" aria-haspopup="dialog" title="Disconnect Merchant Center">Connected</button>
      </div>
    </div>
    <button type="button" class="theme-btn" id="themeToggle" title="Toggle light/dark theme" aria-label="Toggle theme">&#9728;</button>
    <a href="/logout" class="nav-link">Log out</a>
  </div>
</nav>
<div id="mcConnectSuccessOverlay" class="mc-success-overlay" aria-hidden="true">
  <div class="mc-success-modal" role="dialog" aria-modal="true" aria-labelledby="mcSuccessTitle" onclick="event.stopPropagation()">
    <div class="mc-success-icon" aria-hidden="true">&#10003;</div>
    <h3 id="mcSuccessTitle">Merchant Center connected</h3>
    <p>Cartozo can upload products to your Google Merchant account on your behalf.</p>
    <button type="button" class="mc-success-gotit" id="mcConnectSuccessGotIt">Got it</button>
  </div>
</div>
<div id="merchantDisconnectOverlay" class="mc-success-overlay" aria-hidden="true">
  <div class="mc-success-modal" role="dialog" aria-modal="true" aria-labelledby="mcDiscTitle" onclick="event.stopPropagation()">
    <h3 id="mcDiscTitle">Disconnect Merchant Center?</h3>
    <p>Cartozo will stop uploading products to your Google Merchant account until you connect again.</p>
    <div class="mc-confirm-row">
      <button type="button" class="mc-confirm-no" id="merchantDisconnectCancel">No</button>
      <button type="button" class="mc-confirm-yes" id="merchantDisconnectConfirm">Yes, disconnect</button>
    </div>
  </div>
</div>"""


# Theme: only toggles `data-theme` on <html> — logos use CSS (nav-brand, .wt-side, Settings .nav-logo)
ADMIN_THEME_SCRIPT = """
(function(){
  var t = document.getElementById('themeToggle');
  if (!t) return;
  var k = 'hp-theme';
  function g() { return localStorage.getItem(k) || 'dark'; }
  function s(v) {
    document.documentElement.setAttribute('data-theme', v);
    localStorage.setItem(k, v);
    t.textContent = v === 'dark' ? '\u2600' : '\u263E';
  }
  t.onclick = function() { s(g() === 'dark' ? 'light' : 'dark'); };
  s(g());
})();
"""


# Merchant status + disconnect (same behavior as Upload page)
ADMIN_MERCHANT_SCRIPT = """
(function(){
  var mConn = document.getElementById("merchantConnectBtn");
  var navConnected = document.getElementById("navMerchantConnected");
  var merchantConnectedLabel = document.getElementById("merchantConnectedLabel");
  var mcSuccessOv = document.getElementById("mcConnectSuccessOverlay");
  var mcSuccessOk = document.getElementById("mcConnectSuccessGotIt");
  var discOv = document.getElementById("merchantDisconnectOverlay");
  var discCancel = document.getElementById("merchantDisconnectCancel");
  var discConfirm = document.getElementById("merchantDisconnectConfirm");
  function refreshMerchantUi(s) {
    if (!mConn || !navConnected) return;
    if (!s || !s.connected) {
      mConn.style.display = "inline-flex";
      navConnected.classList.remove("visible");
      return;
    }
    mConn.style.display = "none";
    navConnected.classList.add("visible");
    if (merchantConnectedLabel) {
      merchantConnectedLabel.textContent = s.merchant_id ? "Connected · ID " + s.merchant_id : "Connected";
    }
  }
  try {
    var spMc = new URLSearchParams(location.search);
    if (spMc.get("merchant") === "connected" && mcSuccessOv) {
      mcSuccessOv.classList.add("visible");
      mcSuccessOv.setAttribute("aria-hidden", "false");
      spMc.delete("merchant");
      var qMc = spMc.toString();
      history.replaceState({}, "", location.pathname + (qMc ? "?" + qMc : "") + location.hash);
    }
  } catch (e) {}
  if (mcSuccessOk && mcSuccessOv) {
    function closeMcSuccess() {
      mcSuccessOv.classList.remove("visible");
      mcSuccessOv.setAttribute("aria-hidden", "true");
    }
    mcSuccessOk.addEventListener("click", closeMcSuccess);
    mcSuccessOv.addEventListener("click", function(e) { if (e.target === mcSuccessOv) closeMcSuccess(); });
  }
  fetch("/api/merchant/status", { credentials: "same-origin" }).then(function(r) { return r.ok ? r.json() : null; }).then(refreshMerchantUi).catch(function() {});
  function merchantDiscOpen() {
    if (!discOv) return;
    discOv.classList.add("visible");
    discOv.setAttribute("aria-hidden", "false");
  }
  function merchantDiscClose() {
    if (!discOv) return;
    discOv.classList.remove("visible");
    discOv.setAttribute("aria-hidden", "true");
  }
  if (merchantConnectedLabel) {
    merchantConnectedLabel.addEventListener("click", function(e) {
      if (!navConnected || !navConnected.classList.contains("visible")) return;
      e.preventDefault();
      merchantDiscOpen();
    });
  }
  if (discCancel) discCancel.addEventListener("click", merchantDiscClose);
  if (discOv) discOv.addEventListener("click", function(e) { if (e.target === discOv) merchantDiscClose(); });
  if (discConfirm) {
    discConfirm.addEventListener("click", function() {
      merchantDiscClose();
      fetch("/api/merchant/disconnect", { method: "POST", credentials: "same-origin" }).then(function(r) {
        if (r.ok) { refreshMerchantUi({ connected: false }); location.reload(); }
      });
    });
  }
})();
"""
