"""HTML template for /admin/writter/new — 3-step wizard (intent in, structure out)."""


def render_writter_new_article_html(
    *,
    article_type_options: str,
    primary_goal_options: str,
    preset_checkboxes: str,
    admin_top_nav: str,
    admin_shell_nav: str,
    theme_script: str,
    merchant_script: str,
) -> str:
    return (
        PAGE.replace("__ARTICLE_TYPE_OPTS__", article_type_options)
        .replace("__PRIMARY_GOAL_OPTS__", primary_goal_options)
        .replace("__PRESET_CHECKS__", preset_checkboxes)
        .replace("__ADMIN_TOP_NAV__", admin_top_nav)
        .replace("__ADMIN_SHELL_NAV__", admin_shell_nav)
        .replace("__THEME_SCRIPT__", theme_script)
        .replace("__MERCHANT_SCRIPT__", merchant_script)
    )


PAGE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>New article — Writter</title>
  <script>document.documentElement.setAttribute('data-theme', localStorage.getItem('hp-theme') || 'dark');</script>
  <link rel="stylesheet" href="/static/styles.css" />
  <style>
  body { margin:0; font-family:Inter,system-ui,sans-serif; background:#0B0F19; color:#E5E7EB; min-height:100vh; display:flex; flex-direction:column; }
  [data-theme="light"] body { background:#f8fafc; color:#0f172a; }
  .wt-layout { flex:1; display:flex; min-height:0; }
  .wt-side { width:240px; background:#0a0e18; border-right:1px solid rgba(255,255,255,.08); padding:24px 16px; }
  [data-theme="light"] .wt-side { background:#fff; border-color:rgba(15,23,42,.1); }
  .wt-admin-nav a { display:block; padding:10px 14px; border-radius:8px; color:#9ca3af; text-decoration:none; font-size:.9rem; }
  .wt-admin-nav a:hover { background:rgba(255,255,255,.05); color:#fff; }
  .wt-admin-nav a.active { background:rgba(79,70,229,.15); color:#818cf8; font-weight:600; }
  .wt-main { flex:1; padding:32px 40px; max-width:920px; }
  label { display:block; font-size:.78rem; text-transform:uppercase; letter-spacing:.05em; color:#9ca3af; margin:16px 0 6px; }
  input, select, textarea { width:100%; max-width:100%; padding:10px 12px; border-radius:8px; border:1px solid rgba(255,255,255,.12); background:#111827; color:#E5E7EB; font-size:.95rem; box-sizing:border-box; }
  [data-theme="light"] input, [data-theme="light"] select, [data-theme="light"] textarea { background:#fff; border-color:rgba(15,23,42,.15); color:#0f172a; }
  textarea { min-height:80px; }
  .wt-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media(max-width:768px){ .wt-row{ grid-template-columns:1fr; } }
  .wt-btn { margin-top:20px; padding:12px 22px; border-radius:8px; background:#4F46E5; color:#fff; font-weight:600; border:none; cursor:pointer; }
  .wt-btn:disabled { opacity:.6; cursor:not-allowed; }
  .rule-row { display:flex; gap:8px; margin-bottom:8px; align-items:center; flex-wrap:wrap; }
  .visual-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:8px; }
  @media(max-width:900px){ .visual-grid{ grid-template-columns:1fr; } }
  .visual-opt { border:2px solid transparent; border-radius:12px; padding:8px; cursor:pointer; background:rgba(79,70,229,.08); }
  .visual-opt.selected { border-color:#4F46E5; }
  .visual-opt figure { margin:0; }
  .wt-visual-head { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; margin:16px 0 6px; }
  .wt-visual-head label { margin:0; }
  .wt-visual-actions { display:flex; gap:8px; flex-wrap:wrap; }
  .wt-btn-ghost { padding:8px 14px; border-radius:8px; background:transparent; border:1px solid rgba(255,255,255,.2); color:#e5e7eb; font-size:.85rem; font-weight:600; cursor:pointer; }
  .wt-btn-ghost:hover { background:rgba(255,255,255,.06); border-color:rgba(129,140,248,.5); color:#c7d2fe; }
  [data-theme="light"] .wt-btn-ghost { border-color:rgba(15,23,42,.2); color:#334155; }
  #visualMorePanel { display:none; margin-top:12px; padding:14px; border-radius:10px; border:1px solid rgba(255,255,255,.1); background:rgba(79,70,229,.06); }
  #visualMorePanel.wt-open { display:block; }
  #visualMorePanel label { margin-top:0; }
  .err { color:#f87171; margin-top:8px; }
  .wt-loading { position:fixed; inset:0; z-index:10050; background:rgba(11,15,25,.72); display:none; align-items:center; justify-content:center; backdrop-filter:blur(4px); }
  .wt-loading.wt-loading--on { display:flex; }
  .wt-loading-box { background:#111827; border:1px solid rgba(255,255,255,.1); border-radius:16px; padding:32px 40px; text-align:center; max-width:360px; box-shadow:0 24px 48px rgba(0,0,0,.4); }
  [data-theme="light"] .wt-loading-box { background:#fff; border-color:rgba(15,23,42,.12); }
  .wt-spinner { width:44px; height:44px; border:3px solid rgba(129,140,248,.25); border-top-color:#818cf8; border-radius:50%; margin:0 auto 16px; animation:wtspin .85s linear infinite; }
  @keyframes wtspin { to { transform: rotate(360deg); } }
  .wt-loading-box p { margin:0; color:#e5e7eb; font-weight:600; }
  [data-theme="light"] .wt-loading-box p { color:#0f172a; }
  .wt-loading-sub { font-size:.85rem !important; font-weight:400 !important; color:#94a3b8 !important; margin-top:8px !important; }
  .wt-step { display:none; }
  .wt-step.wt-step--active { display:block; }
  .wt-steps-bar { display:flex; gap:8px; align-items:center; margin-bottom:20px; flex-wrap:wrap; }
  .wt-step-pill { padding:6px 12px; border-radius:999px; font-size:.78rem; font-weight:600; background:rgba(255,255,255,.06); color:#94a3b8; }
  .wt-step-pill.wt-on { background:rgba(79,70,229,.25); color:#c7d2fe; }
  .wt-opp-strip { margin:12px 0; padding:12px 14px; border-radius:10px; background:rgba(79,70,229,.12); border:1px solid rgba(129,140,248,.25); font-size:.85rem; color:#cbd5e1; min-height:2.5em; }
  .wt-opp-strip.wt-muted { color:#64748b; }
  .wt-plan-box { margin-top:12px; padding:14px; border-radius:10px; background:#111827; border:1px solid rgba(255,255,255,.08); font-size:.88rem; }
  [data-theme="light"] .wt-plan-box { background:#fff; border-color:rgba(15,23,42,.12); }
  .wt-plan-box ul { margin:8px 0 0 18px; padding:0; }
  .wt-adv { margin-top:16px; padding:0 4px; }
  .wt-adv summary { cursor:pointer; color:#94a3b8; font-size:.88rem; font-weight:600; }
  .wt-adv .wt-adv-body { margin-top:12px; padding-top:12px; border-top:1px solid rgba(255,255,255,.08); }
  .wt-ev-block { display:none; margin-top:8px; }
  .wt-ev-block.wt-on { display:block; }
  .wt-inline-row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:8px 0; }
  .wt-inline-row label { margin:0; text-transform:none; letter-spacing:0; font-size:.88rem; }
  .wt-nav-actions { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:16px; }
  .wt-sh-upload { margin-top:8px; }
  .wt-sh-input { width:auto !important; max-width:100%; padding:8px; font-size:.88rem; cursor:pointer; }
  .wt-sh-hint { font-size:.78rem; color:#64748b; margin:6px 0 10px; text-transform:none; letter-spacing:0; line-height:1.45; }
  .wt-sh-preview { display:flex; flex-direction:column; gap:14px; margin-top:12px; }
  .wt-sh-card { position:relative; border-radius:10px; border:1px solid rgba(255,255,255,.12); background:#111827; padding:10px 10px 12px; max-width:100%; }
  [data-theme="light"] .wt-sh-card { background:#fff; border-color:rgba(15,23,42,.12); }
  .wt-sh-card-top { position:relative; display:inline-block; max-width:280px; }
  .wt-sh-card img { display:block; width:100%; max-height:180px; object-fit:contain; border-radius:6px; background:rgba(0,0,0,.2); }
  .wt-sh-remove { position:absolute; top:4px; right:4px; width:26px; height:26px; border-radius:6px; border:none; background:rgba(0,0,0,.55); color:#fff; cursor:pointer; font-size:16px; line-height:1; padding:0; z-index:1; }
  .wt-sh-remove:hover { background:rgba(239,68,68,.92); }
  .wt-sh-card label { margin:10px 0 4px; font-size:.72rem; text-transform:none; letter-spacing:0; color:#94a3b8; }
  .wt-sh-caption { min-height:64px; font-size:.85rem; line-height:1.45; margin-top:0; }
  .wt-sh-status { font-size:.78rem; color:#94a3b8; margin-top:8px; min-height:1.2em; }
  </style>
</head>
<body>
  __ADMIN_TOP_NAV__
  <div id="wtLoading" class="wt-loading" role="dialog" aria-modal="true" aria-labelledby="wtLoadTitle" aria-hidden="true">
    <div class="wt-loading-box">
      <div class="wt-spinner" aria-hidden="true"></div>
      <p id="wtLoadTitle">Generating article…</p>
      <p class="wt-loading-sub">Please wait — this can take up to a minute.</p>
    </div>
  </div>
  <div class="wt-layout">
    <aside class="wt-side">
      <div style="margin-bottom:20px;"><a href="/admin/writter">← Writter</a></div>
      __ADMIN_SHELL_NAV__
    </aside>
    <main class="wt-main">
      <h1 style="font-size:1.5rem;margin:0 0 8px;">Create article</h1>
      <p style="color:#9ca3af;margin:0 0 16px;">You choose intent (topic + goal); the system proposes structure, proof, and visuals. Defaults come from workspace settings.</p>
      <div class="wt-steps-bar" aria-hidden="true">
        <span class="wt-step-pill wt-on" id="pill1">1 · Idea</span>
        <span class="wt-step-pill" id="pill2">2 · AI plan</span>
        <span class="wt-step-pill" id="pill3">3 · Generate</span>
      </div>
      <form id="f">
        <div id="step1" class="wt-step wt-step--active">
          <h2 style="font-size:1rem;color:#94a3b8;margin:0 0 12px;">Step 1 — Idea</h2>
          <label>Article type</label>
          <select name="article_type" id="article_type">__ARTICLE_TYPE_OPTS__</select>
          <label>Topic</label>
          <input name="topic" id="topic" required placeholder="e.g. How to fix Google Merchant Center disapprovals" />
          <label>Keywords (comma-separated)</label>
          <input name="keywords" id="keywords" placeholder="google merchant center, disapproved products" />
          <label>Primary goal</label>
          <select name="primary_goal" id="primary_goal">__PRIMARY_GOAL_OPTS__</select>
          <div id="oppStrip" class="wt-opp-strip wt-muted">Opportunity updates as you type…</div>
          <div class="wt-nav-actions">
            <button type="button" class="wt-btn" id="btnAnalyze">Analyze &amp; continue</button>
          </div>
        </div>

        <div id="step2" class="wt-step">
          <h2 style="font-size:1rem;color:#94a3b8;margin:0 0 12px;">Step 2 — AI plan</h2>
          <p style="color:#94a3b8;font-size:.88rem;margin:0 0 8px;">Review what the system inferred. Edit the outline if needed.</p>
          <div id="planSummary" class="wt-plan-box"></div>
          <label>Outline (one H2 heading per line)</label>
          <textarea id="outline_sections" rows="7" placeholder="Loaded from blueprint…"></textarea>

          <h3 style="font-size:.95rem;color:#94a3b8;margin:20px 0 8px;">Recommended proof</h3>
          <ul id="proofList" style="margin:0 0 0 18px;color:#cbd5e1;font-size:.88rem;"></ul>
          <p style="font-size:.8rem;color:#64748b;margin:8px 0 0;">Add details below only if you need them.</p>

          <h3 style="font-size:.95rem;color:#94a3b8;margin:20px 0 8px;">Evidence (optional)</h3>
          <div class="wt-inline-row">
            <label><input type="checkbox" id="ev_use_sh" /> Use product screenshots</label>
            <label><input type="checkbox" id="ev_add_dia" /> Add diagram note</label>
            <label><input type="checkbox" id="ev_add_met" /> Add metrics</label>
            <label><input type="checkbox" id="ev_add_uc" /> Add use-case example</label>
          </div>
          <div id="evBlockSh" class="wt-ev-block">
            <label>Product screenshots</label>
            <p class="wt-sh-hint">Upload images (PNG, JPEG, WebP, or GIF — max 5 MB each, up to 20 per upload). For each image, add a short <strong>placement note</strong> (which section or idea it belongs with) so the article generator positions screenshots next to the right text — not at random.</p>
            <div class="wt-sh-upload">
              <input type="file" id="screenshot_files" class="wt-sh-input" accept="image/png,image/jpeg,image/jpg,image/webp,image/gif" multiple />
            </div>
            <p class="wt-sh-status" id="screenshot_upload_status" aria-live="polite"></p>
            <div class="wt-sh-preview" id="screenshot_preview"></div>
          </div>
          <div id="evBlockDia" class="wt-ev-block">
            <label>Diagram / workflow note</label>
            <textarea id="diagram_note" placeholder="What the diagram should show"></textarea>
          </div>
          <div id="evBlockMet" class="wt-ev-block">
            <label>Metrics / numbers to cite</label>
            <textarea id="metrics_manual" placeholder="e.g. −32% disapprovals after 14 days"></textarea>
          </div>
          <div id="evBlockUc" class="wt-ev-block">
            <label>Customer scenario</label>
            <textarea id="customer_scenario"></textarea>
          </div>

          <h3 style="font-size:.95rem;color:#94a3b8;margin:20px 0 8px;">Rules</h3>
          <div id="presetRules">__PRESET_CHECKS__</div>
          <label style="margin-top:12px;">Custom rules (optional)</label>
          <div id="rules"></div>
          <button type="button" class="wt-btn" style="margin-top:8px;padding:8px 14px;font-size:.85rem;" id="addRule">+ Add custom rule</button>

          <h3 style="font-size:.95rem;color:#94a3b8;margin:20px 0 8px;">Visual support</h3>
          <select id="visual_mode" name="visual_mode">
            <option value="auto" selected>Auto suggest (SVG)</option>
            <option value="none">None</option>
            <option value="describe">I’ll describe it</option>
          </select>
          <div id="visualDescribeWrap" style="display:none;margin-top:12px;">
            <label>Describe the visual in one sentence</label>
            <input type="text" id="visual_description" placeholder="e.g. Three-step flow from feed error to fix" />
          </div>
          <div id="visualAutoBlock">
            <div class="wt-visual-head">
              <label style="margin:0;">Pick a diagram variant</label>
              <div class="wt-visual-actions">
                <button type="button" class="wt-btn-ghost" id="btnRegenVisual" title="New variants">Regenerate</button>
                <button type="button" class="wt-btn-ghost" id="btnMoreVisual" aria-expanded="false" aria-controls="visualMorePanel">Layout</button>
              </div>
            </div>
            <input type="hidden" name="visual_index" id="visual_index" value="0" />
            <input type="hidden" name="visual_seed" id="visual_seed" value="0" />
            <div id="visualMorePanel" role="region" aria-label="Visual layout">
              <label>Layout</label>
              <select id="visual_layout" name="visual_layout">
                <option value="horizontal">Horizontal flow</option>
                <option value="vertical">Vertical stack</option>
                <option value="compact">Compact strip</option>
              </select>
            </div>
            <div class="visual-grid" id="visuals"></div>
          </div>

          <details class="wt-adv">
            <summary>Advanced settings</summary>
            <div class="wt-adv-body">
              <div class="wt-row">
                <div>
                  <label>Target audience (override)</label>
                  <input name="audience" id="audience" placeholder="Leave empty to use inferred / workspace default" />
                </div>
                <div>
                  <label>Country / language (override)</label>
                  <input name="country_language" id="country_language" placeholder="Leave empty for workspace default" />
                </div>
              </div>
              <label>Business goal narrative (override)</label>
              <input name="business_goal" id="business_goal" placeholder="Usually derived from primary goal" />
              <label>Quote / testimonial</label>
              <textarea id="quote" rows="3"></textarea>
              <label>Product screen IDs (comma-separated)</label>
              <input name="product_screen_ids" id="product_screen_ids" placeholder="dashboard, feed table" />
            </div>
          </details>

          <div class="wt-nav-actions">
            <button type="button" class="wt-btn-ghost" id="btnBack21">← Back</button>
            <button type="button" class="wt-btn" id="btnToStep3">Continue to generate →</button>
          </div>
        </div>

        <div id="step3" class="wt-step">
          <h2 style="font-size:1rem;color:#94a3b8;margin:0 0 12px;">Step 3 — Generate</h2>
          <label>Generation mode</label>
          <select name="generation_mode" id="generation_mode">
            <option value="fast">Fast — short draft</option>
            <option value="standard" selected>Standard — balanced article</option>
            <option value="authority">Authority — longer, evidence + FAQ bias</option>
          </select>
          <label style="margin-top:16px;"><input type="checkbox" name="publish" id="publish" /> Publish immediately (skipped if quality gates fail)</label>
          <div class="wt-nav-actions">
            <button type="button" class="wt-btn-ghost" id="btnBack32">← Back</button>
            <button type="submit" class="wt-btn" id="submitBtn">Generate &amp; save</button>
          </div>
        </div>
        <p class="err" id="err"></p>
      </form>
    </main>
  </div>
  <script>
  var currentStep = 1;
  var articlePlan = null;
  var oppTimer = null;
  var ruleIdx = 0;
  var screenshotItems = [];

  function renderScreenshotPreview() {
    var el = document.getElementById('screenshot_preview');
    if (!el) return;
    el.innerHTML = '';
    screenshotItems.forEach(function(item, idx) {
      var card = document.createElement('div');
      card.className = 'wt-sh-card';
      var top = document.createElement('div');
      top.className = 'wt-sh-card-top';
      var img = document.createElement('img');
      img.src = item.url || '';
      img.alt = '';
      img.loading = 'lazy';
      var rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'wt-sh-remove';
      rm.title = 'Remove';
      rm.setAttribute('data-idx', String(idx));
      rm.appendChild(document.createTextNode('×'));
      rm.onclick = function() {
        var i = parseInt(rm.getAttribute('data-idx'), 10);
        if (!isNaN(i)) {
          screenshotItems.splice(i, 1);
          renderScreenshotPreview();
        }
      };
      top.appendChild(img);
      top.appendChild(rm);
      var lbl = document.createElement('label');
      lbl.textContent = 'Placement / context for AI (optional but recommended)';
      lbl.setAttribute('for', 'sh_cap_' + idx);
      var ta = document.createElement('textarea');
      ta.id = 'sh_cap_' + idx;
      ta.className = 'wt-sh-caption';
      ta.placeholder = 'e.g. Place under the H2 “Diagnosing feed issues” — Merchant Center disapprovals table';
      ta.rows = 3;
      ta.value = item.caption || '';
      ta.addEventListener('input', function() {
        if (screenshotItems[idx]) screenshotItems[idx].caption = ta.value;
      });
      card.appendChild(top);
      card.appendChild(lbl);
      card.appendChild(ta);
      el.appendChild(card);
    });
  }

  var screenshotFilesEl = document.getElementById('screenshot_files');
  if (screenshotFilesEl) {
    screenshotFilesEl.addEventListener('change', function() {
      var inp = this;
      var files = inp.files;
      if (!files || !files.length) return;
      var st = document.getElementById('screenshot_upload_status');
      if (st) st.textContent = 'Uploading…';
      var fd = new FormData();
      for (var i = 0; i < files.length; i++) {
        fd.append('files', files[i]);
      }
      fetch('/api/admin/writter/upload-screenshots', { method: 'POST', body: fd, credentials: 'same-origin' })
        .then(function(r) {
          if (!r.ok) return r.text().then(function(t) { throw new Error(t || 'Upload failed'); });
          return r.json();
        })
        .then(function(data) {
          var urls = data.urls || [];
          urls.forEach(function(u) { screenshotItems.push({ url: u, caption: '' }); });
          renderScreenshotPreview();
          var evSh = document.getElementById('ev_use_sh');
          if (evSh) { evSh.checked = true; syncEvBlocks(); }
          if (st) st.textContent = urls.length ? ('Uploaded ' + urls.length + ' image(s).') : '';
          inp.value = '';
        })
        .catch(function(e) {
          if (st) st.textContent = e.message || 'Upload failed';
          inp.value = '';
        });
    });
  }

  function setStep(n) {
    currentStep = n;
    document.querySelectorAll('.wt-step').forEach(function(el) { el.classList.remove('wt-step--active'); });
    var s = document.getElementById('step' + n);
    if (s) s.classList.add('wt-step--active');
    for (var i = 1; i <= 3; i++) {
      var p = document.getElementById('pill' + i);
      if (p) p.classList.toggle('wt-on', i === n);
    }
    if (n === 2) {
      syncVisualMode();
      if ((document.getElementById('visual_mode').value || 'auto') === 'auto') loadVisuals();
    }
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function scheduleOpp() {
    clearTimeout(oppTimer);
    oppTimer = setTimeout(fetchOpp, 500);
  }

  function fetchOpp() {
    var topic = document.getElementById('topic').value || '';
    if (topic.length < 3) {
      document.getElementById('oppStrip').classList.add('wt-muted');
      document.getElementById('oppStrip').textContent = 'Opportunity updates as you type…';
      return;
    }
    fetch('/api/admin/writter/opportunity-score', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic: topic,
        keywords: document.getElementById('keywords').value || '',
        article_type: document.getElementById('article_type').value,
        primary_goal: document.getElementById('primary_goal').value,
        audience: '',
        country_language: '',
        business_goal: ''
      })
    }).then(function(r) {
      if (!r.ok) return r.text().then(function(t) { throw new Error(t || 'Score failed'); });
      return r.json();
    })
    .then(function(data) {
      var el = document.getElementById('oppStrip');
      el.classList.remove('wt-muted');
      var sc = data.estimated_value_score != null ? data.estimated_value_score : '—';
      var ang = (data.suggested_angles && data.suggested_angles[0]) ? data.suggested_angles[0] : '';
      var fit = data.product_fit_likelihood != null ? 'Product fit ~' + data.product_fit_likelihood : '';
      el.innerHTML = '<strong>Opportunity: ' + esc(sc) + '/100</strong> · ' + esc(data.search_intent || '') +
        (ang ? ' · ' + esc(ang) : '') + (fit ? ' · ' + esc(fit) : '');
    }).catch(function() { /* silent */ });
  }

  ['topic', 'keywords', 'article_type', 'primary_goal'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('input', scheduleOpp);
    if (el) el.addEventListener('change', scheduleOpp);
  });
  scheduleOpp();

  function populatePlan(plan) {
    articlePlan = plan;
    var box = document.getElementById('planSummary');
    var opp = plan.opportunity || {};
    var sc = opp.estimated_value_score != null ? opp.estimated_value_score : '—';
    var links = plan.internal_link_suggestions || [];
    var linkHtml = links.length ? '<ul>' + links.slice(0, 6).map(function(l) {
      return '<li>' + esc(l.title || l.slug || '') + '</li>';
    }).join('') + '</ul>' : '<p style="margin:0;color:#64748b;">No related articles yet — publish more to unlock internal links.</p>';
    box.innerHTML =
      '<p style="margin:0 0 8px;"><strong>Opportunity:</strong> ' + esc(sc) + '/100 · ' + esc(opp.search_intent || '') + '</p>' +
      '<p style="margin:0 0 8px;"><strong>Audience:</strong> ' + esc(plan.inferred_audience || '') + '</p>' +
      '<p style="margin:0 0 8px;"><strong>Country / language:</strong> ' + esc(plan.country_language || '') + '</p>' +
      '<p style="margin:0 0 8px;"><strong>Goal interpretation:</strong> ' + esc(plan.business_goal_interpretation || '') + '</p>' +
      '<p style="margin:0 0 4px;"><strong>CTA direction:</strong> ' + esc(plan.cta_direction || '') + '</p>' +
      '<p style="margin:0 0 4px;"><strong>Related internal articles:</strong></p>' + linkHtml;
    var outl = plan.blueprint_outline || [];
    document.getElementById('outline_sections').value = outl.join('\n');
    var pr = plan.recommended_proof || [];
    var ul = document.getElementById('proofList');
    ul.innerHTML = pr.length ? pr.map(function(x) { return '<li>' + esc(x) + '</li>'; }).join('') : '<li style="color:#64748b;">—</li>';
    var vm = plan.recommended_visual || {};
    var lay = vm.layout || 'horizontal';
    var sel = document.getElementById('visual_layout');
    if (sel) sel.value = lay;
  }

  document.getElementById('btnAnalyze').onclick = function() {
    var err = document.getElementById('err');
    err.textContent = '';
    var topic = document.getElementById('topic').value.trim();
    if (!topic) { err.textContent = 'Topic is required.'; return; }
    var btn = this;
    btn.disabled = true;
    fetch('/api/admin/writter/article-plan', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic: topic,
        keywords: document.getElementById('keywords').value || '',
        article_type: document.getElementById('article_type').value,
        primary_goal: document.getElementById('primary_goal').value,
        audience: '',
        country_language: '',
        business_goal: ''
      })
    }).then(function(r) { if (!r.ok) return r.text().then(function(t) { throw new Error(t); }); return r.json(); })
    .then(function(plan) {
      populatePlan(plan);
      setStep(2);
    }).catch(function(e) {
      err.textContent = e.message || 'Failed to build plan';
    }).finally(function() { btn.disabled = false; });
  };

  document.getElementById('btnBack21').onclick = function() { setStep(1); };
  document.getElementById('btnToStep3').onclick = function() {
    if (!articlePlan) {
      document.getElementById('err').textContent = 'Run “Analyze & continue” first.';
      return;
    }
    document.getElementById('err').textContent = '';
    setStep(3);
  };
  document.getElementById('btnBack32').onclick = function() { setStep(2); };

  function syncEvBlocks() {
    document.getElementById('evBlockSh').classList.toggle('wt-on', document.getElementById('ev_use_sh').checked);
    document.getElementById('evBlockDia').classList.toggle('wt-on', document.getElementById('ev_add_dia').checked);
    document.getElementById('evBlockMet').classList.toggle('wt-on', document.getElementById('ev_add_met').checked);
    document.getElementById('evBlockUc').classList.toggle('wt-on', document.getElementById('ev_add_uc').checked);
  }
  ['ev_use_sh', 'ev_add_dia', 'ev_add_met', 'ev_add_uc'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener('change', syncEvBlocks); }
  });
  syncEvBlocks();

  function syncVisualMode() {
    var m = document.getElementById('visual_mode').value || 'auto';
    var autoB = document.getElementById('visualAutoBlock');
    var dw = document.getElementById('visualDescribeWrap');
    if (m === 'none') { autoB.style.display = 'none'; dw.style.display = 'none'; return; }
    if (m === 'describe') { autoB.style.display = 'none'; dw.style.display = 'block'; return; }
    autoB.style.display = 'block'; dw.style.display = 'none';
  }
  document.getElementById('visual_mode').addEventListener('change', function() { syncVisualMode(); if (currentStep === 2) loadVisuals(); });

  function loadVisuals() {
    if ((document.getElementById('visual_mode').value || 'auto') !== 'auto') return;
    var topic = document.getElementById('topic').value || '';
    var kw = document.getElementById('keywords').value || '';
    var seed = document.getElementById('visual_seed').value || '0';
    var layout = document.getElementById('visual_layout').value || 'horizontal';
    var params = new URLSearchParams({ topic: topic, keywords: kw, seed: seed, layout: layout });
    fetch('/api/admin/writter/visual-options?' + params.toString(), { credentials: 'same-origin' })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var el = document.getElementById('visuals');
        var opts = data.options || [];
        el.innerHTML = '';
        var pick = parseInt(document.getElementById('visual_index').value, 10) || 0;
        if (pick >= opts.length) pick = 0;
        opts.forEach(function(opt, i) {
          var d = document.createElement('div');
          d.className = 'visual-opt' + (i === pick ? ' selected' : '');
          d.innerHTML = '<div>' + opt.html + '</div><div style="font-size:.75rem;margin-top:6px;color:#9ca3af;">' + (opt.label || '') + '</div>';
          d.onclick = function() {
            document.querySelectorAll('.visual-opt').forEach(function(x) { x.classList.remove('selected'); });
            d.classList.add('selected');
            document.getElementById('visual_index').value = String(i);
          };
          el.appendChild(d);
        });
        document.getElementById('visual_index').value = String(pick);
      });
  }
  document.getElementById('btnRegenVisual').onclick = function() {
    var s = document.getElementById('visual_seed');
    s.value = String(parseInt(s.value || '0', 10) + 1);
    loadVisuals();
  };
  document.getElementById('btnMoreVisual').onclick = function() {
    var p = document.getElementById('visualMorePanel');
    var open = !p.classList.contains('wt-open');
    p.classList.toggle('wt-open', open);
    this.setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  document.getElementById('visual_layout').addEventListener('change', function() { loadVisuals(); });

  document.getElementById('addRule').onclick = function() {
    var d = document.createElement('div');
    d.className = 'rule-row';
    d.innerHTML = '<select name="rule_kind_' + ruleIdx + '"><option value="must_reference_url">Must reference URL</option><option value="must_include_keyword">Must include keyword</option><option value="tone">Tone</option><option value="audience">Audience</option></select>' +
      '<input name="rule_val_' + ruleIdx + '" placeholder="URL or keyword or value" style="flex:1;min-width:180px;" />';
    document.getElementById('rules').appendChild(d);
    ruleIdx++;
  };

  function setLoading(on) {
    var L = document.getElementById('wtLoading');
    if (!L) return;
    if (on) { L.classList.add('wt-loading--on'); L.setAttribute('aria-hidden', 'false'); }
    else { L.classList.remove('wt-loading--on'); L.setAttribute('aria-hidden', 'true'); }
  }

  document.getElementById('f').onsubmit = function(e) {
    e.preventDefault();
    if (currentStep !== 3) {
      document.getElementById('err').textContent = 'Go to step 3 to generate.';
      return;
    }
    if (!articlePlan) {
      document.getElementById('err').textContent = 'Complete step 1–2 first.';
      return;
    }
    var btn = document.getElementById('submitBtn');
    btn.disabled = true;
    document.getElementById('err').textContent = '';
    setLoading(true);
    var rules = [];
    for (var i = 0; i < ruleIdx; i++) {
      var k = document.querySelector('[name=rule_kind_' + i + ']');
      var v = document.querySelector('[name=rule_val_' + i + ']');
      if (!k || !v || !v.value.trim()) continue;
      var kind = k.value;
      var o = { kind: kind };
      if (kind === 'must_reference_url') o.url = v.value.trim();
      else if (kind === 'must_include_keyword') o.value = v.value.trim();
      else if (kind === 'tone') o.value = v.value.trim() || 'professional';
      else if (kind === 'audience') o.value = v.value.trim() || 'e-commerce owners';
      rules.push(o);
    }
    var presets = [];
    document.querySelectorAll('.preset-cb').forEach(function(cb) {
      if (cb.checked) presets.push(cb.getAttribute('data-preset'));
    });
    var outlineRaw = document.getElementById('outline_sections').value || '';
    var outline_sections = outlineRaw.split('\n').map(function(s) { return s.trim(); }).filter(Boolean);
    var body = {
      article_type: document.getElementById('article_type').value,
      topic: document.getElementById('topic').value,
      keywords: document.getElementById('keywords').value,
      primary_goal: document.getElementById('primary_goal').value,
      audience: document.getElementById('audience').value,
      country_language: document.getElementById('country_language').value,
      business_goal: document.getElementById('business_goal').value,
      generation_mode: document.getElementById('generation_mode').value || 'standard',
      evidence: {
        use_product_screenshots: document.getElementById('ev_use_sh').checked,
        add_diagram: document.getElementById('ev_add_dia').checked,
        add_metrics: document.getElementById('ev_add_met').checked,
        add_use_case: document.getElementById('ev_add_uc').checked,
        screenshot_urls: screenshotItems.map(function(x) { return x.url; }),
        screenshots: screenshotItems.map(function(x) { return { url: x.url, caption: (x.caption || '').trim() }; }),
        product_screen_ids: (document.getElementById('product_screen_ids').value || '').split(',').map(function(s) { return s.trim(); }).filter(Boolean),
        metrics_manual: document.getElementById('metrics_manual').value,
        customer_scenario: document.getElementById('customer_scenario').value,
        quote: document.getElementById('quote').value,
        diagram_note: document.getElementById('diagram_note').value,
        recommended_proof_plan: (articlePlan && articlePlan.recommended_proof) ? articlePlan.recommended_proof : null
      },
      rule_presets: presets,
      rules: rules,
      visual_mode: document.getElementById('visual_mode').value || 'auto',
      visual_description: document.getElementById('visual_description').value || '',
      visual_index: parseInt(document.getElementById('visual_index').value, 10) || 0,
      visual_seed: parseInt(document.getElementById('visual_seed').value, 10) || 0,
      visual_layout: document.getElementById('visual_layout').value || 'horizontal',
      publish: document.getElementById('publish').checked,
      outline_sections: outline_sections,
      article_plan_json: articlePlan
    };
    fetch('/api/admin/writter/articles', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function(r) {
      if (!r.ok) return r.text().then(function(t) { throw new Error(t); });
      return r.json();
    }).then(function(data) {
      var id = data.id;
      if (id) {
        window.location.href = '/admin/writter/article/' + id + '/review';
        return;
      }
      setLoading(false);
      window.location.href = '/admin/writter';
    }).catch(function(err) {
      setLoading(false);
      document.getElementById('err').textContent = err.message || 'Failed';
      btn.disabled = false;
    });
  };
  __THEME_SCRIPT__
  __MERCHANT_SCRIPT__
  </script>
</body>
</html>"""
