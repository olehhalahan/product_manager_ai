(function () {
  'use strict';

  var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var C = {
    walnut: '#100904',
    bark: '#382416',
    cork: '#40372e',
    cream: '#ffedd7',
    drift: '#6c5f51',
    ember: '#dc5000',
    green: '#4ade80',
    bar: '#180e08'
  };

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function ease(t) { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); }
  function lerp(a, b, t) { return a + (b - a) * t; }

  function setSize(canvas, ctx) {
    var rect = canvas.getBoundingClientRect();
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = Math.max(2, rect.width);
    var h = Math.max(2, rect.height);
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    return { w: w, h: h };
  }

  function dashedLine(ctx, x0, y0, x1, y1, color, dash) {
    dash = dash || 5;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    var len = Math.hypot(x1 - x0, y1 - y0);
    var steps = Math.ceil(len / (dash * 2));
    for (var i = 0; i < steps; i++) {
      var t0 = (i * dash * 2) / len;
      var t1 = ((i * dash * 2) + dash) / len;
      ctx.moveTo(lerp(x0, x1, t0), lerp(y0, y1, t0));
      ctx.lineTo(lerp(x0, x1, Math.min(t1, 1)), lerp(y0, y1, Math.min(t1, 1)));
    }
    ctx.stroke();
  }

  function drawWindow(ctx, box, opts) {
    opts = opts || {};
    var x = box.x, y = box.y, w = box.w, h = box.h;
    var barH = opts.barH || 32;

    ctx.fillStyle = C.bark;
    ctx.strokeStyle = C.cork;
    ctx.lineWidth = 1;
    ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);

    ctx.fillStyle = C.bar;
    ctx.fillRect(x, y, w, barH);
    dashedLine(ctx, x, y + barH, x + w, y + barH, C.cork);

    ctx.fillStyle = C.drift;
    ctx.font = '500 10px Inter, sans-serif';
    ctx.fillText((opts.filename || 'product_feed.csv').toUpperCase(), x + 12, y + 20);

    var badge = (opts.badge || 'CSV').toUpperCase();
    var bw = ctx.measureText(badge).width + 14;
    ctx.strokeRect(x + w - bw - 10, y + 8, bw, 18);
    ctx.fillText(badge, x + w - bw - 4, y + 20);

    return { x: x + 10, y: y + barH + 8, w: w - 20, h: h - barH - 16 };
  }

  function drawTable(ctx, inner, header, rows, opts) {
    opts = opts || {};
    var colN = header.length;
    var colW = inner.w / colN;
    var y = inner.y + 2;

    ctx.font = '500 9px Inter, sans-serif';
    ctx.fillStyle = C.drift;
    header.forEach(function (h, i) {
      ctx.fillText(h.toUpperCase(), inner.x + i * colW + 4, y + 10);
    });
    dashedLine(ctx, inner.x, y + 16, inner.x + inner.w, y + 16, C.cork);
    y += 22;

    rows.forEach(function (row, ri) {
      var hl = row.highlight || 0;
      if (hl > 0) {
        ctx.fillStyle = 'rgba(56, 36, 22, ' + (0.35 + hl * 0.35) + ')';
        ctx.fillRect(inner.x, y - 3, inner.w, 22);
      }
      row.cells.forEach(function (cell, ci) {
        ctx.fillStyle = (row.colors && row.colors[ci]) || C.cream;
        ctx.font = (ri === 0 ? '500 9px' : '400 10px') + ' Inter, sans-serif';
        var txt = String(cell.text != null ? cell.text : cell);
        var max = (row.max && row.max[ci]) || 16;
        if (txt.length > max) txt = txt.slice(0, max - 1) + '…';
        ctx.fillText(txt, inner.x + ci * colW + 4, y + 11);
      });
      dashedLine(ctx, inner.x, y + 18, inner.x + inner.w, y + 18, C.cork);
      y += 24;
    });
    return y;
  }

  function drawScanline(ctx, inner, p, intensity) {
    intensity = intensity == null ? 1 : intensity;
    var sy = inner.y + inner.h * clamp(p, 0, 1);
    var g = ctx.createLinearGradient(0, sy - 8, 0, sy + 8);
    g.addColorStop(0, 'rgba(220,80,0,0)');
    g.addColorStop(0.5, 'rgba(220,80,0,' + (0.55 * intensity) + ')');
    g.addColorStop(1, 'rgba(220,80,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(inner.x, sy - 8, inner.w, 16);
    ctx.strokeStyle = C.ember;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(inner.x, sy);
    ctx.lineTo(inner.x + inner.w, sy);
    ctx.stroke();
  }

  function drawBadge(ctx, cx, cy, text, pulse) {
    pulse = pulse || 0;
    ctx.font = '500 12px Inter, sans-serif';
    var tw = ctx.measureText(text).width;
    var pw = tw + 36, ph = 28;
    var x = cx - pw / 2, y = cy - ph / 2;
    ctx.fillStyle = 'rgba(220,80,0,' + (0.12 + pulse * 0.08) + ')';
    ctx.beginPath();
    ctx.roundRect(x - 3, y - 3, pw + 6, ph + 6, 16);
    ctx.fill();
    ctx.fillStyle = C.bark;
    ctx.strokeStyle = C.ember;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(x, y, pw, ph, 14);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = C.cream;
    ctx.fillText(text, x + 18, y + 18);
  }

  function drawAmbientGlow(ctx, w, h, t) {
    var gx = w * 0.68 + Math.sin(t * 1.1) * 18;
    var gy = h * 0.38 + Math.cos(t * 0.85) * 12;
    var rad = Math.min(w, h) * 0.35;
    var g = ctx.createRadialGradient(gx, gy, 0, gx, gy, rad);
    g.addColorStop(0, 'rgba(56,36,22,0.45)');
    g.addColorStop(1, 'rgba(16,9,4,0)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
  }

  function feedDemoFrame(ctx, w, h, phase, compact) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = C.walnut;
    ctx.fillRect(0, 0, w, h);
    drawAmbientGlow(ctx, w, h, phase * 10);

    if (!compact) {
      ctx.fillStyle = C.drift;
      ctx.font = '500 10px Inter, sans-serif';
      ctx.fillText('CARTOZO FEED-1', 16, 22);
      ctx.fillStyle = C.cream;
      ctx.font = '500 16px Inter, sans-serif';
      ctx.fillText('FULL CATALOG OPTIMIZATION', 16, 42);
    }

    var pad = compact ? 10 : 16;
    var top = compact ? 12 : 52;
    var box = { x: pad, y: top, w: w - pad * 2, h: h - top - (compact ? 14 : 28) };
    var inner = drawWindow(ctx, box, { badge: 'CSV' });

    var before = [
      ['12345', 'Generic Chair Black', '42'],
      ['12346', 'Blue Shirt', '38'],
      ['12347', 'Running Shoes', '51']
    ];
    var after = [
      ['12345', 'IKEA Black Dining Chair Modern', '91'],
      ['12346', 'Mens Oxford Shirt Blue Slim Fit', '86'],
      ['12347', 'Nike Air Max 90 White Running', '88']
    ];

    var morph0 = 0.25, morph1 = 0.65;
    var scan0 = 0.15, scan1 = 0.3;
    if (phase > scan0 && phase < scan1) {
      drawScanline(ctx, inner, (phase - scan0) / (scan1 - scan0), 1);
    }

    var rows = [];
    for (var i = 0; i < before.length; i++) {
      var rp = ease(clamp((phase - morph0 - i * 0.05) / (morph1 - morph0), 0, 1));
      var title = before[i][1];
      if (rp > 0.45) title = after[i][1];
      if (rp > 0.45 && rp < 0.55) {
        title = after[i][1].slice(0, Math.max(1, Math.floor(after[i][1].length * ((rp - 0.45) / 0.1))));
      }
      var score = Math.round(lerp(+before[i][2], +after[i][2], ease(Math.max(0, (rp - 0.35) / 0.65))));
      rows.push({
        cells: [before[i][0], title, String(score)],
        colors: [C.drift, rp > 0.5 ? C.cream : C.drift, score >= 80 ? C.ember : C.drift],
        highlight: rp > 0.2 && rp < 0.75 ? 0.4 : 0,
        max: [6, compact ? 18 : 26, 4]
      });
    }

    var label = phase < 0.18 ? 'BEFORE' : (phase < morph1 ? 'OPTIMIZING…' : 'AFTER');
    var labelColor = phase < 0.18 ? C.drift : (phase < morph1 ? C.ember : C.green);
    ctx.fillStyle = labelColor;
    ctx.font = '500 9px Inter, sans-serif';
    ctx.fillText(label, inner.x, inner.y - 6);

    drawTable(ctx, inner, ['id', 'title', 'score'], rows);

    if (phase > 0.72 && !compact) {
      drawBadge(ctx, w / 2, h - 14, 'MERCHANT READY', Math.sin(phase * 20) * 0.5 + 0.5);
    }
  }

  /* --- Hero + cinema video modal --- */
  function openVideoModal(src) {
    var modal = qs('#hpVideoModal');
    var video = qs('#hpModalVideo');
    if (!modal || !video) return;
    var source = video.querySelector('source');
    if (source) source.src = src;
    else video.src = src;
    video.load();
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    video.currentTime = 0;
    video.play().catch(function () {});
    document.body.style.overflow = 'hidden';
  }

  function closeVideoModal() {
    var modal = qs('#hpVideoModal');
    var video = qs('#hpModalVideo');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    if (video) video.pause();
    document.body.style.overflow = '';
  }

  function initHeroVideo() {
    var trigger = qs('#hpHeroVideo');
    var modal = qs('#hpVideoModal');
    if (!trigger || !modal) return;
    var closeBtn = qs('#hpVideoModalClose');
    trigger.addEventListener('click', function () {
      openVideoModal('/static/home-media/cartozo-demo.webm');
    });
    if (closeBtn) closeBtn.addEventListener('click', closeVideoModal);
    modal.addEventListener('click', function (e) { if (e.target === modal) closeVideoModal(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeVideoModal();
    });
  }

  /* --- Live hero preview canvas (replaces empty poster feel) --- */
  function initHeroPreview() {
    var wrap = qs('#hpHeroVideo');
    var canvas = qs('#hpHeroPreview');
    if (!wrap || !canvas) return;
    var ctx = canvas.getContext('2d');
    var start = performance.now();

    function tick(now) {
      if (!wrap.isConnected) return;
      var sz = setSize(canvas, ctx);
      var phase = ((now - start) / 1000 % 9) / 9;
      feedDemoFrame(ctx, sz.w, sz.h, phase, true);
      if (!prefersReduced) requestAnimationFrame(tick);
    }
    if (prefersReduced) {
      var sz = setSize(canvas, ctx);
      feedDemoFrame(ctx, sz.w, sz.h, 0.75, true);
    } else {
      requestAnimationFrame(tick);
    }
    window.addEventListener('resize', function () {
      var sz = setSize(canvas, ctx);
      feedDemoFrame(ctx, sz.w, sz.h, 0.5, true);
    }, { passive: true });
  }

  /* --- Split text --- */
  function splitText(el) {
    if (!el || el.dataset.splitDone) return;
    var words = el.textContent.trim().split(/\s+/);
    el.textContent = '';
    el.dataset.splitDone = '1';
    words.forEach(function (word, wi) {
      var line = document.createElement('span');
      line.className = 'hp-split-line';
      line.style.display = wi === words.length - 1 ? 'inline' : 'block';
      var inner = document.createElement('span');
      inner.className = 'hp-split-word';
      inner.textContent = word + (wi < words.length - 1 ? ' ' : '');
      inner.style.transitionDelay = (wi * 0.04) + 's';
      line.appendChild(inner);
      el.appendChild(line);
    });
  }

  function initSplitReveal() {
    qsa('[data-split]').forEach(splitText);
    if (prefersReduced) {
      qsa('.hp-split-word').forEach(function (w) { w.classList.add('visible'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        qsa('.hp-split-word', entry.target).forEach(function (w, i) {
          setTimeout(function () { w.classList.add('visible'); }, i * 35);
        });
        io.unobserve(entry.target);
      });
    }, { threshold: 0.2, rootMargin: '0px 0px -8% 0px' });
    qsa('[data-split]').forEach(function (el) { io.observe(el); });
  }

  /* --- Rich background: grid + linked particles --- */
  function initBgCanvas() {
    if (prefersReduced) return;
    var canvas = qs('#hpBgCanvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var dots = [];
    var t = 0;

    function resize() {
      var sz = setSize(canvas, ctx);
      dots = [];
      var n = Math.floor((sz.w * sz.h) / 28000);
      for (var i = 0; i < n; i++) {
        dots.push({
          x: Math.random() * sz.w,
          y: Math.random() * sz.h,
          r: Math.random() * 1.4 + 0.4,
          vx: (Math.random() - 0.5) * 0.12,
          vy: (Math.random() - 0.5) * 0.12
        });
      }
    }

    function frame() {
      t += 0.016;
      var sz = setSize(canvas, ctx);
      ctx.clearRect(0, 0, sz.w, sz.h);

      ctx.strokeStyle = 'rgba(64,55,46,0.08)';
      ctx.lineWidth = 1;
      var grid = 56;
      var off = (t * 8) % grid;
      for (var gx = -grid; gx < sz.w + grid; gx += grid) {
        ctx.beginPath();
        ctx.moveTo(gx - off, 0);
        ctx.lineTo(gx - off, sz.h);
        ctx.stroke();
      }
      for (var gy = -grid; gy < sz.h + grid; gy += grid) {
        ctx.beginPath();
        ctx.moveTo(0, gy - off * 0.5);
        ctx.lineTo(sz.w, gy - off * 0.5);
        ctx.stroke();
      }

      dots.forEach(function (d) {
        d.x += d.vx; d.y += d.vy;
        if (d.x < 0) d.x = sz.w;
        if (d.x > sz.w) d.x = 0;
        if (d.y < 0) d.y = sz.h;
        if (d.y > sz.h) d.y = 0;
      });

      for (var i = 0; i < dots.length; i++) {
        for (var j = i + 1; j < dots.length; j++) {
          var dx = dots[i].x - dots[j].x;
          var dy = dots[i].y - dots[j].y;
          var dist = Math.hypot(dx, dy);
          if (dist < 90) {
            ctx.strokeStyle = 'rgba(255,237,215,' + (0.06 * (1 - dist / 90)) + ')';
            ctx.beginPath();
            ctx.moveTo(dots[i].x, dots[i].y);
            ctx.lineTo(dots[j].x, dots[j].y);
            ctx.stroke();
          }
        }
      }

      dots.forEach(function (d) {
        ctx.beginPath();
        ctx.fillStyle = 'rgba(255,237,215,' + (0.12 + Math.sin(t + d.x * 0.02) * 0.06) + ')';
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        ctx.fill();
      });

      requestAnimationFrame(frame);
    }

    resize();
    window.addEventListener('resize', resize, { passive: true });
    requestAnimationFrame(frame);
  }

  /* --- Scroll-scrubbed void scene + idle motion --- */
  function initVoidScene() {
    var section = qs('.hp-scene--reveal');
    var canvas = qs('#hpVoidCanvas');
    if (!section || !canvas) return;
    var ctx = canvas.getContext('2d');
    var scrollP = 0;
    var idleT = 0;
    var rafId = null;

    function render() {
      var sz = setSize(canvas, ctx);
      var phase = clamp(scrollP * 0.55 + 0.12 + Math.sin(idleT * 0.6) * 0.04, 0, 1);
      var tilt = lerp(-0.08, 0.06, scrollP);

      ctx.clearRect(0, 0, sz.w, sz.h);
      ctx.save();
      ctx.translate(sz.w / 2, sz.h / 2 + lerp(24, 0, scrollP));
      ctx.rotate(tilt);
      ctx.scale(0.88 + scrollP * 0.12, 0.88 + scrollP * 0.12);

      var bw = sz.w * 0.82, bh = sz.h * 0.78;
      ctx.translate(-bw / 2, -bh / 2);
      feedDemoFrame(ctx, bw, bh, phase, false);
      ctx.restore();

      idleT += 0.016;
      rafId = requestAnimationFrame(render);
    }

    function onScroll() {
      var rect = section.getBoundingClientRect();
      var total = section.offsetHeight - window.innerHeight;
      scrollP = total > 0 ? clamp(-rect.top / total, 0, 1) : 0;
    }

    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    if (prefersReduced) {
      scrollP = 0.7;
      var sz = setSize(canvas, ctx);
      feedDemoFrame(ctx, sz.w, sz.h, 0.75, false);
    } else {
      render();
    }
  }

  /* --- Powered section with animated score bars --- */
  function initPoweredSection() {
    var stage = qs('#hpPoweredStage');
    var cursor = qs('#hpPoweredCursor');
    if (!stage) return;
    var rows = qsa('.hp-powered-row', stage);

    rows.forEach(function (row) {
      var scoreEl = row.querySelector('.hp-powered-score');
      if (!scoreEl) return;
      var target = parseInt(scoreEl.dataset.score || scoreEl.textContent, 10) || 0;
      scoreEl.dataset.score = String(target);
      scoreEl.innerHTML = '<span class="hp-powered-score-num">' + target + '</span><span class="hp-powered-score-bar"><span class="hp-powered-score-fill"></span></span>';
      var fill = scoreEl.querySelector('.hp-powered-score-fill');
      if (fill) fill.style.width = target + '%';
    });

    if (!cursor) return;
    stage.addEventListener('mousemove', function (e) {
      var r = stage.getBoundingClientRect();
      cursor.style.left = (e.clientX - r.left) + 'px';
      cursor.style.top = (e.clientY - r.top) + 'px';
      rows.forEach(function (row) {
        var rr = row.getBoundingClientRect();
        var over = e.clientY >= rr.top && e.clientY <= rr.bottom;
        row.classList.toggle('is-active', over);
        if (over) {
          var fill = row.querySelector('.hp-powered-score-fill');
          if (fill) fill.style.transform = 'scaleX(1.02)';
        }
      });
    });
    stage.addEventListener('mouseleave', function () {
      rows.forEach(function (row) {
        row.classList.remove('is-active');
        var fill = row.querySelector('.hp-powered-score-fill');
        if (fill) fill.style.transform = '';
      });
    });
  }

  function initCinema() {
    qsa('.hp-cinema-play').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var src = btn.getAttribute('data-cinema-src');
        if (src) openVideoModal(src);
      });
    });
    qsa('.hp-cinema-card').forEach(function (card) {
      card.addEventListener('click', function () {
        var src = card.getAttribute('data-cinema-src');
        if (src) openVideoModal(src);
      });
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          var src = card.getAttribute('data-cinema-src');
          if (src) openVideoModal(src);
        }
      });
    });
    var videos = qsa('.hp-cinema-media video');
    if (!videos.length) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var v = entry.target;
        var card = v.closest('.hp-cinema-card');
        if (entry.isIntersecting) {
          v.play().catch(function () {});
          if (card) card.classList.add('is-playing');
        } else {
          v.pause();
          if (card) card.classList.remove('is-playing');
        }
      });
    }, { threshold: 0.3 });
    videos.forEach(function (v) {
      v.muted = true;
      v.loop = true;
      v.playsInline = true;
      io.observe(v);
    });
  }

  function initHeroParallax() {
    if (prefersReduced) return;
    var voidEl = qs('.hp-hero-void');
    if (!voidEl) return;
    window.addEventListener('scroll', function () {
      voidEl.style.transform = 'translate3d(0,' + (window.scrollY * 0.1) + 'px,0)';
    }, { passive: true });
  }

  function boot() {
    initHeroVideo();
    initHeroPreview();
    initSplitReveal();
    initVoidScene();
    initPoweredSection();
    initCinema();
    initHeroParallax();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
