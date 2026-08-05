'use strict';

const BATCH_SIZE = 100;
const POLL_MS    = 60_000;
const MAX_AGE_MS = 14 * 86_400_000;

let allIds       = new Set();
let displayedIds = new Set();
let pending      = [];
let searchActive = false;
let fetchCount   = 0;
let activeFilter = '';

// ── Helpers ────────────────────────────────────────────────

function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function timeAgo(iso) {
    const ms = Date.now() - new Date(iso).getTime();
    const m  = Math.floor(ms / 60_000);
    if (m < 1)  return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
}

function setStatus(msg) {
    document.getElementById('last-fetch').textContent = msg;
    document.getElementById('shown-count').textContent = `${displayedIds.size} shown`;
}

// ── Card ───────────────────────────────────────────────────

function makeCard(h) {
    const score = Math.round((h.score || 0) * 100);
    const cross = h.cross_source_count > 1 ? ` · +${h.cross_source_count - 1}` : '';
    const div   = document.createElement('div');
    div.className      = 'card';
    div.dataset.id     = h.id;
    div.dataset.source = (h.source || '').toLowerCase();
    div.dataset.title  = (h.title  || '').toLowerCase();
    div.innerHTML = `
      <div class="card-meta">
        <span class="source-tag">${esc(h.source)}</span>
        <span class="cross">${esc(cross)}</span>
        <span class="age">${timeAgo(h.published)}</span>
      </div>
      <div class="headline">${esc(h.title)}</div>
      <div class="score-bar"><div class="score-fill" style="width:${score}%"></div></div>`;
    div.addEventListener('click', () => openModal(h));
    return div;
}

// ── Render ─────────────────────────────────────────────────

function renderBatch(batch) {
    const feed    = document.getElementById('feed');
    const sentinel= document.getElementById('sentinel');
    const loading = document.getElementById('loading');
    if (loading) loading.remove();

    const frag = document.createDocumentFragment();
    for (const h of batch) {
        frag.appendChild(makeCard(h));
        displayedIds.add(h.id);
    }
    // Insert before sentinel so sentinel stays at bottom
    feed.insertBefore(frag, sentinel);

    if (activeFilter) applyFilter(activeFilter);
    setStatus(`Last fetch: ${new Date().toLocaleTimeString()}`);
}

function deliverBatch() {
    if (!pending.length) return;
    const batch = pending.splice(0, BATCH_SIZE);
    renderBatch(batch);
}

// ── Infinite scroll ────────────────────────────────────────

const observer = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting && pending.length > 0) {
        deliverBatch();
    }
}, { rootMargin: '200px' });

// ── Fetch ──────────────────────────────────────────────────

async function fetchHeadlines(q) {
    const url = q ? `/api/headlines?q=${encodeURIComponent(q)}` : '/api/headlines';
    setStatus(q ? `Searching "${q}"…` : 'Fetching…');
    try {
        const res  = await fetch(url);
        const data = await res.json();
        const cutoff = Date.now() - MAX_AGE_MS;

        if (q) {
            const fresh = data.filter(h => new Date(h.published).getTime() > cutoff);
            if (fresh.length) renderBatch(fresh);
            setStatus(`${fresh.length} results for "${q}"`);
            closeSearch();
        } else {
            const novel = data.filter(h =>
                !allIds.has(h.id) && new Date(h.published).getTime() > cutoff
            );
            novel.forEach(h => allIds.add(h.id));
            pending.push(...novel);
            fetchCount++;
            if (fetchCount === 1 && pending.length) {
                deliverBatch();
                observer.observe(document.getElementById('sentinel'));
            } else {
                setStatus(`Last fetch: ${new Date().toLocaleTimeString()}`);
            }
        }
    } catch {
        setStatus('Fetch error — will retry');
    }
}

// ── Filter ─────────────────────────────────────────────────

function applyFilter(query) {
    const q = query.trim().toLowerCase();
    activeFilter = q;
    const cards = [...document.querySelectorAll('.card')];
    if (!q) { cards.forEach(c => c.style.display = ''); return; }
    // Same logic as Python TUI: if query matches any source name → source filter; else → title filter
    const sourceMatch = cards.some(c => c.dataset.source.includes(q));
    cards.forEach(c => {
        const hit = sourceMatch ? c.dataset.source.includes(q) : c.dataset.title.includes(q);
        c.style.display = hit ? '' : 'none';
    });
}

// ── Search ─────────────────────────────────────────────────

function openSearch() {
    searchActive = true;
    document.getElementById('search-bar').classList.remove('hidden');
    document.getElementById('btn-search').classList.add('active');
    const inp = document.getElementById('search-input');
    inp.value = activeFilter;
    inp.focus();
    inp.select();
}

function closeSearch(keepFilter = false) {
    searchActive = false;
    document.getElementById('search-bar').classList.add('hidden');
    document.getElementById('btn-search').classList.remove('active');
    if (!keepFilter) applyFilter('');
}

document.getElementById('btn-search').addEventListener('click', () =>
    searchActive ? closeSearch() : openSearch()
);
document.getElementById('search-input').addEventListener('input',  e => applyFilter(e.target.value));
document.getElementById('search-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        const q = e.target.value.trim();
        if (!q) return;
        const visible = [...document.querySelectorAll('.card')]
            .some(c => c.style.display !== 'none');
        if (visible) {
            closeSearch(true); // local filter matched — keep it, close bar
        } else {
            fetchHeadlines(q); // nothing matched locally — fetch from API
        }
    }
    if (e.key === 'Escape') closeSearch();
});

// ── Modal ──────────────────────────────────────────────────

function openModal(h) {
    document.getElementById('modal-source').textContent = h.source;
    document.getElementById('modal-age').textContent    = timeAgo(h.published);
    document.getElementById('modal-title').textContent  = h.title;
    const desc = document.getElementById('modal-desc');
    desc.textContent  = h.description || '';
    desc.style.display = h.description ? '' : 'none';
    document.getElementById('modal-link').href = h.url;
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.body.style.overflow = '';
}

document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
});

// ── Keyboard (desktop) ─────────────────────────────────────

document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === '/')       { e.preventDefault(); openSearch(); }
    if (e.key === 'Escape')  closeModal();
    if (e.key === 'q' || e.key === 'Q') window.close();
});

// ── Service worker ─────────────────────────────────────────

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// ── PWA install prompt ──────────────────────────────────────

let deferredInstall = null;
let installTimer    = null;

const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;

function hideInstallBanner() {
    clearTimeout(installTimer);
    document.getElementById('install-banner').classList.add('hidden');
}

window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    if (isStandalone) return;
    deferredInstall = e;
    document.getElementById('install-banner').classList.remove('hidden');
    installTimer = setTimeout(hideInstallBanner, 10000); // auto-hide after 10s
});

window.addEventListener('appinstalled', () => {
    deferredInstall = null;
    hideInstallBanner();
});

document.getElementById('install-btn').addEventListener('click', async () => {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    await deferredInstall.userChoice;
    deferredInstall = null;
    hideInstallBanner();
});

// ── Boot ───────────────────────────────────────────────────

fetchHeadlines();
setInterval(fetchHeadlines, POLL_MS);
