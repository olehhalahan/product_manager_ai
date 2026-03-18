/**
 * Smooth page transitions - fade in on load, fade out before navigation
 */
(function() {
    const DURATION = 280;
    const style = document.createElement('style');
    style.textContent = `
        body { transition: opacity ${DURATION}ms ease; }
        body.page-transition-out { opacity: 0; pointer-events: none; }
    `;
    document.head.appendChild(style);

    function isInternalLink(el) {
        if (el.tagName !== 'A' || !el.href) return false;
        try {
            const url = new URL(el.href);
            if (url.origin !== location.origin) return false;
            if (el.target === '_blank') return false;
            if (el.hasAttribute('download')) return false;
            if (url.pathname === location.pathname) return false;
            return true;
        } catch { return false; }
    }

    function navigate(url) {
        document.body.style.opacity = '';
        document.body.classList.add('page-transition-out');
        setTimeout(function() { location.href = url; }, DURATION);
    }

    document.addEventListener('click', function(e) {
        const a = e.target.closest('a');
        if (!a || !isInternalLink(a)) return;
        if (e.ctrlKey || e.metaKey || e.shiftKey) return;
        e.preventDefault();
        navigate(a.href);
    }, true);

    document.body.style.opacity = '0';
    requestAnimationFrame(function() {
        document.body.style.opacity = '1';
    });
})();
