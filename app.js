'use strict';

const BATCH_SIZE = 100;
const POLL_MS    = 5_000;
const MAX_AGE_MS = 14 * 86_400_000;

let allIds       = new Set();
let displayedIds = new Set();
const headlineMap = new Map();
let pending      = [];
let searchActive = false;
let fetchCount   = 0;
let activeFilter = '';
let currentLang  = 'en';

// ── Favourites ─────────────────────────────────────────────

const FAV_KEY        = 'wsf_favorites';
const READ_KEY       = 'wsf_read';
const PREFS_KEY      = 'wsf_prefs';
const SEARCH_HIST_KEY = 'wsf_search_hist';
const THEME_KEY      = 'wsf_theme';

function getPrefs() {
    try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{"categories":{},"sources":{}}'); }
    catch { return { categories: {}, sources: {} }; }
}

function learnFromRead(h) {
    const prefs = getPrefs();
    const cat = (h.category || '').toLowerCase();
    const src = (h.source   || '').toLowerCase();
    if (cat) prefs.categories[cat] = (prefs.categories[cat] || 0) + 1;
    if (src) prefs.sources[src]    = (prefs.sources[src]    || 0) + 1;
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch {}
}

// ── #13 Haptic feedback ────────────────────────────────────
function vibrate(ms = 8) {
    try { navigator.vibrate?.(ms); } catch {}
}

// ── #11 Search history ─────────────────────────────────────
function getSearchHistory() {
    try { return JSON.parse(localStorage.getItem(SEARCH_HIST_KEY) || '[]'); }
    catch { return []; }
}
function saveToSearchHistory(q) {
    if (!q) return;
    let hist = getSearchHistory().filter(x => x !== q);
    hist.unshift(q);
    hist = hist.slice(0, 8);
    try { localStorage.setItem(SEARCH_HIST_KEY, JSON.stringify(hist)); } catch {}
}
function renderSearchHistory() {
    const hist = getSearchHistory();
    const el = document.getElementById('search-history');
    if (!hist.length) { el.classList.add('hidden'); return; }
    el.innerHTML = hist.map(q =>
        `<button class="hist-chip">${esc(q)}</button>`
    ).join('') + `<button class="hist-clear">Clear</button>`;
    el.classList.remove('hidden');
    el.querySelectorAll('.hist-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            vibrate(6);
            document.getElementById('search-input').value = btn.textContent;
            applyFilter(btn.textContent);
            el.classList.add('hidden');
        });
    });
    el.querySelector('.hist-clear').addEventListener('click', () => {
        try { localStorage.removeItem(SEARCH_HIST_KEY); } catch {}
        el.classList.add('hidden');
    });
}

// ── #14 Theme toggle ───────────────────────────────────────
function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.getElementById('theme-toggle').textContent = theme === 'light' ? '🌙' : '☀️';
    try { localStorage.setItem(THEME_KEY, theme); } catch {}
}
function toggleTheme() {
    vibrate(6);
    const current = document.documentElement.dataset.theme || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
}

function getReadIds() {
    try { return new Set(JSON.parse(localStorage.getItem(READ_KEY) || '[]')); }
    catch { return new Set(); }
}

function markRead(id) {
    const ids = getReadIds();
    if (ids.has(id)) return;
    ids.add(id);
    // Keep only the last 500 to avoid unbounded growth
    const trimmed = [...ids].slice(-500);
    try { localStorage.setItem(READ_KEY, JSON.stringify(trimmed)); } catch {}
    document.querySelectorAll(`.card[data-id="${id}"]`).forEach(c => c.classList.add('read'));
}

function getFavs() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY) || '[]'); }
    catch { return []; }
}

function saveFavs(favs) {
    localStorage.setItem(FAV_KEY, JSON.stringify(favs));
}

function isFav(id) {
    return getFavs().some(f => f.id === id);
}

function toggleFav(h, starEl) {
    let favs = getFavs();
    const idx = favs.findIndex(f => f.id === h.id);
    if (idx === -1) {
        favs.push(h);
        saveFavs(favs);
        document.querySelectorAll(`.card[data-id="${h.id}"] .star-btn`).forEach(s => {
            s.textContent = '★'; s.classList.add('starred');
        });
        // hide duplicate in normal feed
        document.querySelectorAll(`.card[data-id="${h.id}"]`).forEach(c => {
            if (!c.closest('#fav-section')) c.style.display = 'none';
        });
        addFavCard(h);
    } else {
        favs.splice(idx, 1);
        saveFavs(favs);
        document.querySelectorAll(`.card[data-id="${h.id}"] .star-btn`).forEach(s => {
            s.textContent = '☆'; s.classList.remove('starred');
        });
        // restore card in normal feed
        document.querySelectorAll(`.card[data-id="${h.id}"]`).forEach(c => {
            if (!c.closest('#fav-section')) c.style.display = '';
        });
        const sec = document.getElementById('fav-section');
        if (sec) {
            const fc = sec.querySelector(`.card[data-id="${h.id}"]`);
            if (fc) fc.remove();
            if (!sec.querySelector('.card')) sec.remove();
        }
    }
}

function addFavCard(h) {
    let sec = document.getElementById('fav-section');
    if (!sec) {
        sec = document.createElement('div');
        sec.id = 'fav-section';
        const hdr = document.createElement('div');
        hdr.className = 'fav-header';
        hdr.textContent = '★  PINNED';
        sec.appendChild(hdr);
        const feed = document.getElementById('feed');
        feed.insertBefore(sec, feed.firstChild);
    }
    sec.appendChild(makeCard(h));
}

function renderFavSection() {
    getFavs().forEach(h => addFavCard(h));
}

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
    const score    = Math.round((h.score || 0) * 100);
    const cross    = h.cross_source_count > 1 ? ` · +${h.cross_source_count - 1}` : '';
    const starred  = isFav(h.id);
    const div      = document.createElement('div');
    div.className      = getReadIds().has(h.id) ? 'card read' : 'card';
    headlineMap.set(h.id, h);
    div.dataset.id     = h.id;
    div.dataset.source   = (h.source   || '').toLowerCase();
    div.dataset.title    = (h.title    || '').toLowerCase();
    div.dataset.category = (h.category || '').toLowerCase();
    const imgHtml = h.image
        ? `<img class="card-img" src="${esc(h.image)}" alt="" loading="lazy" onerror="this.remove()" onload="if(this.naturalWidth<200||this.naturalHeight<120)this.remove()">`
        : '';
    div.innerHTML = `
      <div class="card-meta">
        <span class="source-tag">${esc(h.source)}</span>
        <span class="cross">${esc(cross)}</span>
        <span class="age">${timeAgo(h.published)}</span>
        <button class="star-btn${starred ? ' starred' : ''}" aria-label="Favourite">${starred ? '★' : '☆'}</button>
      </div>
      ${imgHtml}
      <div class="headline">${esc(h.title)}</div>
      <div class="score-bar"><div class="score-fill" style="width:${score}%"></div></div>`;
    div.querySelector('.star-btn').addEventListener('click', e => {
        e.stopPropagation();
        vibrate(12);
        toggleFav(h, e.currentTarget);
    });
    div.addEventListener('click', () => { vibrate(8); div.classList.add('read'); openModal(h); });
    return div;
}

// ── Render ─────────────────────────────────────────────────

function renderBatch(batch, prepend = false, live = false) {
    const feed    = document.getElementById('feed');
    const sentinel= document.getElementById('sentinel');
    const loading = document.getElementById('loading');
    if (loading) loading.remove();

    const frag = document.createDocumentFragment();
    for (const h of batch) {
        const card = makeCard(h);
        if (live) card.dataset.live = '1';
        if (isFav(h.id)) card.style.display = 'none';
        frag.appendChild(card);
        displayedIds.add(h.id);
    }

    if (prepend) {
        const firstCard = feed.querySelector('.card');
        feed.insertBefore(frag, firstCard || sentinel);
    } else {
        feed.insertBefore(frag, sentinel);
    }

    if (activeFilter) {
        applyFilter(activeFilter);
    } else if (activeCategory !== 'all') {
        applyCategory(activeCategory);
    }
    renderTrending();
    updateTopCard();
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
    const base = q ? `/api/headlines?q=${encodeURIComponent(q)}` : `/api/headlines?lang=${currentLang}`;
    const url  = base;
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
            fetchCount++;
            if (fetchCount === 1) {
                pending.push(...novel);
                if (pending.length) {
                    deliverBatch();
                    observer.observe(document.getElementById('sentinel'));
                }
            } else if (novel.length) {
                // Auto-refresh: new articles go to the top immediately
                renderBatch(novel, true);
                setStatus(`${novel.length} new · ${new Date().toLocaleTimeString()}`);
            } else {
                setStatus(`Last fetch: ${new Date().toLocaleTimeString()}`);
            }
        }
    } catch {
        setStatus('Fetch error — will retry');
    }
}

// ── Smart search ────────────────────────────────────────────

const _NOISE = new Set([
    'headlines','news','articles','stories','latest','recent','show','from',
    'about','give','find','get','the','and','for','with','that','this','just',
    'only','all','any','some','more','most','have','been','will','specific',
    'related','regarding','please','me','i','want','need','looking','fetch',
    'search','tell','display','list','give','ones','those','these'
]);

const _CAT_ALIAS = {
    'india': 'india',         'indian': 'india',
    'sports': 'sports',       'sport': 'sports',
    'cricket': 'sports',      'football': 'sports',     'soccer': 'sports',
    'tech': 'tech',           'technology': 'tech',     'ai': 'tech',
    'finance': 'finance',     'business': 'finance',    'market': 'finance',
    'stock': 'finance',       'economy': 'finance',
    'health': 'health',       'medical': 'health',      'medicine': 'health',
    'science': 'science',     'space': 'science',
    'entertainment': 'entertainment', 'movie': 'entertainment',
    'film': 'entertainment',  'bollywood': 'entertainment',
    'politics': 'politics',   'political': 'politics',  'election': 'politics',
    'nature': 'nature',       'wildlife': 'nature',     'environment': 'nature',
    'world': 'geo-political', 'global': 'geo-political','international': 'geo-political',
};

function _extractIntent(raw) {
    const words = raw.trim().toLowerCase().split(/\W+/).filter(w => w.length >= 2);
    let category = null;
    const keywords = [];
    for (const w of words) {
        if (_CAT_ALIAS[w]) { category = _CAT_ALIAS[w]; }
        else if (!_NOISE.has(w) && w.length >= 3) { keywords.push(w); }
    }
    return { category, keywords };
}

function applyFilter(query) {
    const q = query.trim().toLowerCase();
    activeFilter = q;
    document.querySelectorAll('.card[data-live]').forEach(c => c.remove());
    document.getElementById('search-not-found').classList.add('hidden');

    // Restore all non-fav cards first
    document.querySelectorAll('.card').forEach(c => {
        if (!c.closest('#fav-section')) {
            c.style.display = isFav(c.dataset.id) ? 'none' : '';
        }
    });

    if (!q) return;

    const { category, keywords } = _extractIntent(q);
    const cards = [...document.querySelectorAll('.card:not([style*="display: none"])')];

    // Score each card
    const scored = cards.map(c => {
        let score = 0;
        if (category && c.dataset.category === category) score += 10;
        for (const kw of keywords) {
            if (c.dataset.title.includes(kw))  score += 3;
            if (c.dataset.source.includes(kw)) score += 1;
            if (c.dataset.category.includes(kw)) score += 2;
        }
        // Exact phrase bonus
        if (keywords.length && c.dataset.title.includes(keywords.join(' '))) score += 5;
        return { c, score };
    });

    const threshold = category ? 10 : (keywords.length ? 1 : 0);
    const matched = scored.filter(x => x.score >= threshold)
                          .sort((a, b) => b.score - a.score)
                          .map(x => x.c);

    if (!matched.length && !category && keywords.length) {
        // Nothing found locally — live fetch fallback
        cards.forEach(c => c.style.display = 'none');
        document.getElementById('search-not-found').textContent = 'Searching…';
        document.getElementById('search-not-found').classList.remove('hidden');
        fetchLive(query.trim());
        return;
    }

    // Show only matched, in relevance order
    const feed = document.getElementById('feed');
    const sentinel = document.getElementById('sentinel');
    const matchedSet = new Set(matched);
    cards.forEach(c => { c.style.display = matchedSet.has(c) ? '' : 'none'; });
    matched.forEach(c => feed.insertBefore(c, sentinel));

    if (!matched.length) {
        document.getElementById('search-not-found').textContent = 'Not found!';
        document.getElementById('search-not-found').classList.remove('hidden');
    }
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
    if (!activeFilter) renderSearchHistory();
}

function closeSearch(keepFilter = false) {
    searchActive = false;
    document.getElementById('search-bar').classList.add('hidden');
    document.getElementById('search-history').classList.add('hidden');
    document.getElementById('btn-search').classList.remove('active');
    document.getElementById('search-trigger').classList.remove('active');
    if (!keepFilter) {
        applyFilter('');
        document.getElementById('search-not-found').classList.add('hidden');
    }
}

document.getElementById('btn-search').addEventListener('click', () =>
    searchActive ? closeSearch() : openSearch()
);
document.getElementById('search-trigger').addEventListener('click', () => {
    if (searchActive) {
        closeSearch();
        document.getElementById('search-trigger').classList.remove('active');
    } else {
        openSearch();
        document.getElementById('search-trigger').classList.add('active');
    }
});
document.getElementById('search-input').addEventListener('input', e => {
    const v = e.target.value;
    applyFilter(v);
    document.getElementById('search-history').classList.toggle('hidden', v.length > 0);
});
document.getElementById('search-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
        const q = e.target.value.trim();
        if (q) { saveToSearchHistory(q); track('search', { query: q, lang: currentLang }); }
        closeSearch(true);
    }
    if (e.key === 'Escape') closeSearch();
});

// ── Live search ─────────────────────────────────────────────

async function fetchLive(q) {
    try {
        const res  = await fetch(`/api/headlines?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        document.getElementById('search-not-found').classList.add('hidden');
        if (!data.length) {
            document.getElementById('search-not-found').textContent = 'Not found!';
            document.getElementById('search-not-found').classList.remove('hidden');
            return;
        }
        renderBatch(data, true, true);
        // Make live cards visible — applyFilter may have hidden everything
        document.querySelectorAll('.card[data-live]').forEach(c => c.style.display = '');
        setStatus(`${data.length} results for "${q}"`);
    } catch {
        document.getElementById('search-not-found').textContent = 'Not found!';
        document.getElementById('search-not-found').classList.remove('hidden');
    }
}

// ── Category filter ────────────────────────────────────────

let activeCategory = 'all';

const CATEGORY_MAP = {
    'all': null,
    // 'world': 'geo-political',
    // 'india': 'india',
    'politics': 'politics',
    'sports': 'sports',
    'tech': 'tech',
    'finance': 'finance',
    'science': 'science',
    'health': 'health',
    'entertainment': 'entertainment',
    // 'fashion': 'fashion',
    // 'explore': 'explore',
    'nature': 'nature',
};

function applyForYou() {
    const prefs = getPrefs();
    const hasPrefs = Object.keys(prefs.categories).length > 0 || Object.keys(prefs.sources).length > 0;
    const emptyEl = document.getElementById('foryou-empty');

    emptyEl.classList.add('hidden');
    if (!hasPrefs) {
        document.querySelectorAll('.card').forEach(c => {
            if (!c.closest('#fav-section')) c.style.display = 'none';
        });
        return;
    }
    const feed = document.getElementById('feed');
    const sentinel = document.getElementById('sentinel');
    const cards = [...document.querySelectorAll('.card')].filter(c => !c.closest('#fav-section'));

    const scored = cards.map(c => {
        const score = (prefs.categories[c.dataset.category] || 0) * 2
                    + (prefs.sources[c.dataset.source]       || 0);
        return { c, score };
    }).filter(x => x.score > 0).sort((a, b) => b.score - a.score);

    const visible = new Set(scored.map(x => x.c));
    cards.forEach(c => { c.style.display = visible.has(c) ? '' : 'none'; });
    scored.forEach(({ c }) => feed.insertBefore(c, sentinel));
    updateTopCard();
}

function applyCategory(cat) {
    activeCategory = cat;
    document.querySelectorAll('.cat-tab').forEach(b =>
        b.classList.toggle('active', b.dataset.cat === cat)
    );
    document.getElementById('foryou-empty').classList.add('hidden');
    if (cat === 'foryou') { applyForYou(); return; }
    const filter = CATEGORY_MAP[cat];
    document.querySelectorAll('.card').forEach(c => {
        if (!filter) { c.style.display = ''; return; }
        c.style.display = c.dataset.category === filter ? '' : 'none';
    });
    updateTopCard();
}

document.querySelectorAll('.cat-tab').forEach(btn =>
    btn.addEventListener('click', () => { vibrate(6); applyCategory(btn.dataset.cat); })
);

// ── Language switcher ──────────────────────────────────────

function switchLang(lang) {
    currentLang = lang;
    document.getElementById('lang-btn').textContent = lang === 'bn' ? 'বাং' : 'EN';
    document.querySelectorAll('.lang-opt').forEach(b =>
        b.classList.toggle('active', b.dataset.lang === lang)
    );
    allIds.clear(); displayedIds.clear();
    pending = []; fetchCount = 0; activeFilter = '';
    document.getElementById('feed').querySelectorAll('.card').forEach(c => c.remove());
    document.getElementById('search-not-found').classList.add('hidden');
    const loading = document.createElement('div');
    loading.id = 'loading';
    loading.innerHTML = '<div class="spinner"></div>Fetching news for you. Read it. Enjoy it.';
    document.getElementById('feed').insertBefore(loading, document.getElementById('sentinel'));
    fetchHeadlines();
}

document.getElementById('lang-btn').addEventListener('click', e => {
    e.stopPropagation();
    document.getElementById('lang-dropdown').classList.toggle('hidden');
});
document.querySelectorAll('.lang-opt').forEach(btn => {
    btn.addEventListener('click', () => {
        document.getElementById('lang-dropdown').classList.add('hidden');
        if (btn.dataset.lang !== currentLang) {
        track('language_switch', { lang: btn.dataset.lang });
        switchLang(btn.dataset.lang);
    }
    });
});
document.addEventListener('click', () =>
    document.getElementById('lang-dropdown').classList.add('hidden')
);

// ── #7 Article summary ─────────────────────────────────────

function _summarize(raw) {
    if (!raw) return '';
    const d = document.createElement('div');
    d.innerHTML = raw;
    const text = (d.textContent || d.innerText || '').replace(/\s+/g, ' ').trim();
    const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
    return sentences.slice(0, 3).join(' ').trim();
}

// ── #8 Trending topics ──────────────────────────────────────

const _STOP = new Set([
    'the','a','an','and','or','but','in','on','at','to','for','of','with','is',
    'are','was','were','has','have','had','be','been','being','by','from','as',
    'it','its','this','that','these','those','he','she','they','we','you','i',
    'my','his','her','their','our','your','will','would','could','should','may',
    'might','can','do','does','did','not','no','nor','so','yet','both','either',
    'neither','than','then','when','where','who','which','how','what','why',
    'after','before','since','while','new','says','said','over','more','less',
    'also','just','up','out','into','about','through','during','after','amid',
]);

function computeTrending() {
    const freq = {};
    document.querySelectorAll('.card').forEach(c => {
        (c.dataset.title || '').toLowerCase().split(/\W+/).forEach(w => {
            if (w.length < 4 || _STOP.has(w)) return;
            freq[w] = (freq[w] || 0) + 1;
        });
    });
    return Object.entries(freq)
        .filter(([, n]) => n >= 2)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8)
        .map(([w]) => w);
}

function renderTrending() {
    const words = computeTrending();
    const bar = document.getElementById('trending-bar');
    if (!words.length) { bar.classList.add('hidden'); return; }
    bar.innerHTML = '<span class="trend-label">Trending</span>'
        + words.map(w => `<button class="trend-chip">${esc(w)}</button>`).join('');
    bar.classList.remove('hidden');
    bar.querySelectorAll('.trend-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            vibrate(6);
            track('trending_click', { word: btn.textContent });
            applyFilter(btn.textContent);
        });
    });
}

// ── #9 Related articles ─────────────────────────────────────

function findRelated(h) {
    const titleWords = new Set(
        (h.title || '').toLowerCase().split(/\W+/).filter(w => w.length >= 4 && !_STOP.has(w))
    );
    const hCat = (h.category || '').toLowerCase();
    return [...document.querySelectorAll('.card:not(#fav-section .card)')]
        .filter(c => c.dataset.id !== h.id && c.style.display !== 'none')
        .map(c => {
            let score = 0;
            if (c.dataset.category === hCat) score += 3;
            (c.dataset.title || '').toLowerCase().split(/\W+/).forEach(w => {
                if (titleWords.has(w)) score++;
            });
            return { id: c.dataset.id, score };
        })
        .filter(x => x.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, 3)
        .map(x => headlineMap.get(x.id))
        .filter(Boolean);
}

// ── Modal ──────────────────────────────────────────────────

function _cleanDesc(raw) {
    if (!raw) return '';
    const d = document.createElement('div');
    d.innerHTML = raw;
    return (d.textContent || d.innerText || '').replace(/\s+/g, ' ').trim();
}

function openModal(h) {
    track('article_click', { title: h.title, source: h.source, lang: currentLang });
    markRead(h.id);
    learnFromRead(h);
    document.getElementById('modal-source').textContent = h.source;
    document.getElementById('modal-age').textContent    = timeAgo(h.published);
    document.getElementById('modal-title').textContent  = h.title;
    const modalImg = document.getElementById('modal-img');
    if (h.image) { modalImg.src = h.image; modalImg.hidden = false; }
    else { modalImg.hidden = true; modalImg.src = ''; }
    const summary = _summarize(h.description);
    const summaryWrap = document.getElementById('modal-summary-wrap');
    const desc = document.getElementById('modal-desc');
    if (summary) {
        desc.textContent = summary;
        summaryWrap.hidden = false;
    } else {
        summaryWrap.hidden = true;
    }

    // Related articles (#9)
    const related = findRelated(h);
    const relWrap = document.getElementById('modal-related');
    const relList = document.getElementById('modal-related-list');
    if (related.length) {
        relList.innerHTML = '';
        related.forEach(r => {
            const item = document.createElement('div');
            item.className = 'related-item';
            item.innerHTML = `<span class="related-source">${esc(r.source)}</span><span class="related-title">${esc(r.title)}</span>`;
            item.addEventListener('click', () => { vibrate(8); openModal(r); });
            relList.appendChild(item);
        });
        relWrap.hidden = false;
    } else {
        relWrap.hidden = true;
    }
    document.getElementById('modal-link').href = h.url;
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.body.style.overflow = '';
}

document.getElementById('modal-close').addEventListener('click', closeModal);

document.getElementById('modal-share').addEventListener('click', async () => {
    vibrate(8);
    const title = document.getElementById('modal-title').textContent;
    const url   = document.getElementById('modal-link').href;
    if (navigator.share) {
        try { await navigator.share({ title, url }); } catch {}
    } else {
        try {
            await navigator.clipboard.writeText(url);
            const toast = document.getElementById('share-toast');
            toast.classList.remove('hidden');
            setTimeout(() => toast.classList.add('hidden'), 2000);
        } catch {}
    }
});
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

// ── Analytics ──────────────────────────────────────────────

const _sessionStart = Date.now();

function track(name, data) {
    window.va?.('event', { name, data });
    window.umami?.track(name, data);
}

// Time spent — fires when user leaves or hides the tab
function trackSession() {
    const secs = Math.round((Date.now() - _sessionStart) / 1000);
    track('session_end', { seconds: secs, lang: currentLang });
}
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') trackSession();
});
window.addEventListener('pagehide', trackSession);

// ── Top card highlight ─────────────────────────────────────

function updateTopCard() {
    const statusH = document.getElementById('status-strip').offsetHeight;
    const cards   = [...document.querySelectorAll('.card')].filter(c => c.style.display !== 'none');
    let topCard   = null;
    for (const card of cards) {
        if (card.getBoundingClientRect().bottom > statusH) {
            topCard = card;
            break;
        }
    }
    cards.forEach(c => c.classList.remove('top-card'));
    if (topCard) topCard.classList.add('top-card');
}

window.addEventListener('scroll',   () => requestAnimationFrame(updateTopCard), { passive: true });
document.addEventListener('scroll', () => requestAnimationFrame(updateTopCard), { passive: true });

// ── Disclaimer ─────────────────────────────────────────────

(function () {
    if (!sessionStorage.getItem('disclaimer_ok')) {
        // shown once per session
    } else {
        document.getElementById('disclaimer-overlay').classList.add('hidden');
    }
    document.getElementById('disclaimer-ok').addEventListener('click', () => {
        sessionStorage.setItem('disclaimer_ok', '1');
        document.getElementById('disclaimer-overlay').classList.add('hidden');
    });
})();

// ── #12 Skeleton loading ───────────────────────────────────

function showSkeleton() {
    const loading = document.getElementById('loading');
    if (!loading) return;
    loading.innerHTML = Array(5).fill(0).map(() => `
        <div class="skeleton-card">
          <div class="sk sk-meta"></div>
          <div class="sk sk-img"></div>
          <div class="sk sk-line long"></div>
          <div class="sk sk-line med"></div>
        </div>`).join('');
}

// ── #15 Country news ───────────────────────────────────────

const COUNTRY_NAMES = {
    US:'🇺🇸 United States', GB:'🇬🇧 United Kingdom', IN:'🇮🇳 India',
    BD:'🇧🇩 Bangladesh',    AU:'🇦🇺 Australia',       CA:'🇨🇦 Canada',
    DE:'🇩🇪 Germany',       FR:'🇫🇷 France',           JP:'🇯🇵 Japan',
    BR:'🇧🇷 Brazil',
};
let activeCountry = null;

function openCountrySheet() {
    vibrate(6);
    document.getElementById('country-overlay').classList.remove('hidden');
}
function closeCountrySheet() {
    document.getElementById('country-overlay').classList.add('hidden');
}

async function switchCountry(code) {
    vibrate(8);
    closeCountrySheet();
    activeCountry = code;
    allIds.clear(); displayedIds.clear();
    pending = []; fetchCount = 0; activeFilter = '';
    document.getElementById('feed').querySelectorAll('.card').forEach(c => c.remove());
    document.getElementById('trending-bar').classList.add('hidden');
    document.getElementById('country-btn').textContent = code === null ? '🌍' : (COUNTRY_NAMES[code]?.slice(0, 4) || '🌍');
    showSkeleton();
    setStatus(`Fetching ${COUNTRY_NAMES[code] || code} news…`);
    try {
        const res  = await fetch(`/api/headlines?country=${encodeURIComponent(code)}`);
        const data = await res.json();
        const cutoff = Date.now() - MAX_AGE_MS;
        const fresh = data.filter(h => new Date(h.published).getTime() > cutoff);
        fresh.forEach(h => allIds.add(h.id));
        fetchCount++;
        pending.push(...fresh);
        if (pending.length) {
            deliverBatch();
            observer.observe(document.getElementById('sentinel'));
        }
    } catch {
        setStatus('Fetch error — will retry');
    }
}

document.getElementById('country-btn').addEventListener('click', openCountrySheet);
document.getElementById('country-close').addEventListener('click', closeCountrySheet);
document.getElementById('country-overlay').addEventListener('click', e => {
    if (e.target === document.getElementById('country-overlay')) closeCountrySheet();
});
document.querySelectorAll('.country-btn').forEach(btn => {
    btn.addEventListener('click', () => switchCountry(btn.dataset.code));
});

// ── Boot ───────────────────────────────────────────────────

// Apply saved theme
(function () {
    const saved = localStorage.getItem(THEME_KEY) || 'dark';
    applyTheme(saved);
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
})();

showSkeleton();
renderFavSection();
fetchHeadlines();
setInterval(fetchHeadlines, POLL_MS);
setTimeout(updateTopCard, 1000);
setTimeout(updateTopCard, 3000);
setTimeout(updateTopCard, 6000);
