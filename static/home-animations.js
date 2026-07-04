(function () {
  'use strict';

  var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  /* --- Hero video modal (ORYZO PLAY pattern) --- */
  function initHeroVideo() {
    var trigger = qs('#hpHeroVideo');
    var modal = qs('#hpVideoModal');
    if (!trigger || !modal) return;

    var video = qs('#hpModalVideo');
    var closeBtn = qs('#hpVideoModalClose');

    function openModal() {
      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
      if (video) {
        video.currentTime = 0;
        video.play().catch(function () {});
      }
      document.body.style.overflow = 'hidden';
    }

    function closeModal() {
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
      if (video) video.pause();
      document.body.style.overflow = '';
    }

    trigger.addEventListener('click', openModal);
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', function (e) {
      if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
    });
  }

  /* --- Split text scroll reveal --- */
  function splitText(el) {
    if (!el || el.dataset.splitDone) return;
    var text = el.textContent.trim();
    var words = text.split(/\s+/);
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
    }, { threshold: 0.25, rootMargin: '0px 0px -10% 0px' });
    qsa('[data-split]').forEach(function (el) { io.observe(el); });
  }

  /* --- Background drift canvas --- */
  function initBgCanvas() {
    if (prefersReduced) return;
    var canvas = qs('#hpBgCanvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var w = 0;
    var h = 0;
    var dots = [];
    var t = 0;

    function resize() {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      dots = [];
      var n = Math.floor((w * h) / 42000);
      for (var i = 0; i < n; i++) {
        dots.push({
          x: Math.random() * w,
          y: Math.random() * h,
          r: Math.random() * 1.2 + 0.3,
          vx: (Math.random() - 0.5) * 0.08,
          vy: (Math.random() - 0.5) * 0.08,
          a: Math.random() * 0.25 + 0.08
        });
      }
    }

    function frame() {
      t += 0.016;
      ctx.clearRect(0, 0, w, h);
      dots.forEach(function (d) {
        d.x += d.vx;
        d.y += d.vy;
        if (d.x < 0) d.x = w;
        if (d.x > w) d.x = 0;
        if (d.y < 0) d.y = h;
        if (d.y > h) d.y = 0;
        ctx.beginPath();
        ctx.fillStyle = 'rgba(255, 237, 215, ' + (d.a + Math.sin(t + d.x * 0.01) * 0.04) + ')';
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        ctx.fill();
      });
      requestAnimationFrame(frame);
    }

    resize();
    window.addEventListener('resize', resize, { passive: true });
    requestAnimationFrame(frame);
  }

  /* --- Scroll-scrubbed void feed card (3D canvas) --- */
  function initVoidScene() {
    var section = qs('.hp-scene--reveal');
    var canvas = qs('#hpVoidCanvas');
    if (!section || !canvas) return;

    var ctx = canvas.getContext('2d');
    var dpr = Math.min(window.devicePixelRatio || 1, 2);

    function drawFeedCard(progress) {
      var rect = canvas.getBoundingClientRect();
      var cw = rect.width;
      var ch = rect.height;
      if (cw < 2 || ch < 2) return;
      canvas.width = cw * dpr;
      canvas.height = ch * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);

      var rotY = -0.35 + progress * 0.7;
      var rotX = 0.18 - progress * 0.12;
      var scale = 0.72 + progress * 0.28;
      var lift = (1 - progress) * 40;

      ctx.save();
      ctx.translate(cw / 2, ch / 2 + lift);
      ctx.scale(scale, scale);

      var w = cw * 0.78;
      var h = ch * 0.62;

      ctx.transform(
        Math.cos(rotY), Math.sin(rotX) * 0.25,
        -Math.sin(rotY) * 0.15, Math.cos(rotX),
        0, 0
      );

      ctx.fillStyle = 'rgba(56, 36, 22, 0.92)';
      ctx.strokeStyle = '#40372e';
      ctx.lineWidth = 1;
      roundRect(ctx, -w / 2, -h / 2, w, h, 0);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#ffedd7';
      ctx.font = '500 11px Inter, sans-serif';
      ctx.fillText('PRODUCT_FEED.CSV', -w / 2 + 16, -h / 2 + 24);

      var rows = [
        ['id', 'title', 'score'],
        ['12345', progress < 0.45 ? 'Generic Chair Black' : 'IKEA Dining Chair Black Modern', progress < 0.45 ? '42' : '91'],
        ['12346', progress < 0.55 ? 'Shoes' : 'Nike Air Max 90 White Mens Running', progress < 0.55 ? '38' : '88']
      ];

      var y0 = -h / 2 + 44;
      rows.forEach(function (row, ri) {
        var yy = y0 + ri * 28;
        row.forEach(function (cell, ci) {
          var xx = -w / 2 + 16 + ci * (w / 3.2);
          if (ri === 0) ctx.fillStyle = '#6c5f51';
          else if (ci === 2) ctx.fillStyle = progress > 0.4 && ri > 0 ? '#dc5000' : '#6c5f51';
          else ctx.fillStyle = '#ffedd7';
          ctx.font = (ri === 0 ? '500 9px' : '400 10px') + ' Inter, sans-serif';
          var txt = String(cell);
          if (txt.length > 22) txt = txt.slice(0, 20) + '…';
          ctx.fillText(txt.toUpperCase(), xx, yy);
        });
        if (ri > 0) {
          ctx.strokeStyle = 'rgba(64, 55, 46, 0.55)';
          ctx.beginPath();
          ctx.moveTo(-w / 2 + 12, yy + 8);
          ctx.lineTo(w / 2 - 12, yy + 8);
          ctx.stroke();
        }
      });

      ctx.restore();
    }

    function roundRect(c, x, y, width, height, radius) {
      c.beginPath();
      c.moveTo(x + radius, y);
      c.lineTo(x + width - radius, y);
      c.quadraticCurveTo(x + width, y, x + width, y + radius);
      c.lineTo(x + width, y + height - radius);
      c.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
      c.lineTo(x + radius, y + height);
      c.quadraticCurveTo(x, y + height, x, y + height - radius);
      c.lineTo(x, y + radius);
      c.quadraticCurveTo(x, y, x + radius, y);
      c.closePath();
    }

    function update() {
      var rect = section.getBoundingClientRect();
      var total = section.offsetHeight - window.innerHeight;
      var scrolled = Math.min(Math.max(-rect.top, 0), total);
      var progress = total > 0 ? scrolled / total : 0;
      drawFeedCard(progress);
    }

    if (prefersReduced) {
      drawFeedCard(1);
      return;
    }

    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    update();
  }

  /* --- Powered section: cursor + row highlight --- */
  function initPoweredSection() {
    var stage = qs('#hpPoweredStage');
    var cursor = qs('#hpPoweredCursor');
    if (!stage || !cursor) return;

    var rows = qsa('.hp-powered-row', stage);

    stage.addEventListener('mousemove', function (e) {
      var r = stage.getBoundingClientRect();
      cursor.style.left = (e.clientX - r.left) + 'px';
      cursor.style.top = (e.clientY - r.top) + 'px';
      rows.forEach(function (row) {
        var rr = row.getBoundingClientRect();
        var over = e.clientY >= rr.top && e.clientY <= rr.bottom;
        row.classList.toggle('is-active', over);
      });
    });

    stage.addEventListener('mouseleave', function () {
      rows.forEach(function (row) { row.classList.remove('is-active'); });
    });
  }

  /* --- Gallery: auto-play videos when visible --- */
  function initGallery() {
    var videos = qsa('.hp-gallery-item video');
    if (!videos.length) return;

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var v = entry.target;
        if (entry.isIntersecting) {
          v.play().catch(function () {});
        } else {
          v.pause();
        }
      });
    }, { threshold: 0.55 });

    videos.forEach(function (v) {
      v.muted = true;
      v.loop = true;
      v.playsInline = true;
      io.observe(v);
    });
  }

  /* --- Parallax hero void --- */
  function initHeroParallax() {
    if (prefersReduced) return;
    var voidEl = qs('.hp-hero-void');
    if (!voidEl) return;
    window.addEventListener('scroll', function () {
      var y = window.scrollY;
      voidEl.style.transform = 'translate3d(0, ' + (y * 0.12) + 'px, 0)';
    }, { passive: true });
  }

  function boot() {
    initHeroVideo();
    initSplitReveal();
    initBgCanvas();
    initVoidScene();
    initPoweredSection();
    initGallery();
    initHeroParallax();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
