'use strict';

const BATCH_SIZE    = 100;
const POLL_MS       = 60_000;
const MAX_AGE_MS    = 6 * 86_400_000;

let allIds      = new Set();
let displayedIds= new Set();
let pending     = [];
let paused      = true;
let searchActive= false;
let fetchCount  = 0;

// ── Helpers ────────────────────────────────────────────────

function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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

// ── Card creation ──────────────────────────────────────────

function makeCard(h) {
    const score = Math.round((h.score || 0) * 100);
    const cross = h.cross_source_count > 1 ? ` · +${h.cross_source_count - 1}` : '';
    const div   = document.createElement('div');
    div.className     = 'card';
    div.dataset.id    = h.id;
    div.dataset.source= (h.source || '').toLowerCase();
    div.dataset.title = (h.title  || '').toLowerCase();
    div.innerHTML = `
      <div class="card-meta">
        <span class="source-tag">${esc(h.source)}</span>
        <span class="cross">${esc(cross)}</span>
        <span class="age">${timeAgo(h.published)}</span>
      </div>
      <div class="headline">${esc(h.title)}</div>
      <div class="score-bar"><div class="score-fill" style="width:${score}%"></div></div>`;
    div.addEventListener('click', () => window.open(h.url, '_blank', 'noopener'));
    return div;
}

// ── Render batch ───────────────────────────────────────────

function renderBatch(batch) {
    const feed    = document.getElementById('feed');
    const loading = document.getElementById('loading');
    if (loading) loading.remove();

    const frag = document.createDocumentFragment();
    for (const h of batch) {
        frag.appendChild(makeCard(h));
        displayedIds.add(h.id);
    }
    feed.insertBefore(frag, feed.firstChild);
    window.scrollTo({ top: 0, behavior: 'smooth' });

    if (searchActive) {
        applyFilter(document.getElementById('search-input').value);
    }
}

// ── Deliver next batch from pending ───────────────────────

function deliverBatch() {
    if (!pending.length) { paused = true; updateUI(); return; }
    const batch = pending.splice(0, BATCH_SIZE);
    renderBatch(batch);
    paused = true;
    updateUI();
}

// ── Fetch from API ─────────────────────────────────────────

async function fetchHeadlines(q) {
    const url = q ? `/api/headlines?q=${encodeURIComponent(q)}` : '/api/headlines';
    setStatus(q ? `Searching "${q}"…` : 'Fetching…');
    try {
        const res  = await fetch(url);
        const data = await res.json();
        const cutoff = Date.now() - MAX_AGE_MS;

        if (q) {
            // Search results — render directly, bypass batch
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
            } else {
                updateUI();
                setStatus(`Last fetch: ${new Date().toLocaleTimeString()}`);
            }
        }
    } catch (e) {
        setStatus('Fetch error — will retry');
    }
}

// ── Filter ─────────────────────────────────────────────────

function applyFilter(query) {
    const q     = query.trim().toLowerCase();
    const cards = [...document.querySelectorAll('.card')];
    if (!q) { cards.forEach(c => c.style.display = ''); return; }
    const srcMatch = cards.some(c => c.dataset.source.includes(q));
    cards.forEach(c => {
        c.style.display = (srcMatch ? c.dataset.source : c.dataset.title).includes(q)
            ? '' : 'none';
    });
}

// ── Search UI ──────────────────────────────────────────────

function openSearch() {
    searchActive = true;
    document.getElementById('search-bar').classList.remove('hidden');
    document.getElementById('paused-banner').classList.add('hidden');
    document.getElementById('btn-search').classList.add('active');
    const inp = document.getElementById('search-input');
    inp.value = '';
    inp.focus();
}

function closeSearch() {
    searchActive = false;
    document.getElementById('search-bar').classList.add('hidden');
    document.getElementById('btn-search').classList.remove('active');
    applyFilter('');
    updateUI();
}

// ── UI updates ─────────────────────────────────────────────

function updateUI() {
    const banner = document.getElementById('paused-banner');
    const count  = document.getElementById('buffer-count');
    const btnR   = document.getElementById('btn-resume');

    if (paused && !searchActive) {
        banner.classList.remove('hidden');
        count.textContent = `${pending.length} buffered`;
        btnR.querySelector('span').textContent = pending.length ? `Load ${Math.min(pending.length, BATCH_SIZE)}` : 'Resume';
    } else {
        banner.classList.add('hidden');
    }

    document.getElementById('shown-count').textContent = `${displayedIds.size} shown`;
}

function setStatus(msg) {
    document.getElementById('last-fetch').textContent = msg;
}

// ── Keyboard (desktop) ─────────────────────────────────────

document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT') {
        if (e.key === 'Escape') { closeSearch(); e.preventDefault(); }
        if (e.key === 'Enter')  { fetchHeadlines(e.target.value.trim()); }
        return;
    }
    if (e.key === '/')  { e.preventDefault(); openSearch(); }
    if (e.key === 'r' || e.key === 'R') { doResume(); }
    if (e.key === 'q' || e.key === 'Q') { window.close(); }
});

// ── Button handlers ────────────────────────────────────────

function doResume() {
    if (pending.length) { deliverBatch(); }
    else { paused = false; updateUI(); }
}

document.getElementById('btn-search').addEventListener('click', () => {
    searchActive ? closeSearch() : openSearch();
});
document.getElementById('btn-resume').addEventListener('click', doResume);
document.getElementById('btn-quit').addEventListener('click', () => window.close());

document.getElementById('search-input').addEventListener('input', e => {
    applyFilter(e.target.value);
});
document.getElementById('search-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        const q = e.target.value.trim();
        if (q) fetchHeadlines(q);
    }
    if (e.key === 'Escape') closeSearch();
});

// ── Service worker ─────────────────────────────────────────

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// ── Boot ───────────────────────────────────────────────────

fetchHeadlines();
setInterval(fetchHeadlines, POLL_MS);
