const SHELL_CACHE = 'wsf-shell-v2';
const DATA_CACHE  = 'wsf-data-v1';
const IMG_CACHE   = 'wsf-img-v1';
const ALL_CACHES  = [SHELL_CACHE, DATA_CACHE, IMG_CACHE];

const SHELL_URLS = [
    '/',
    '/index.html',
    '/app.js',
    '/app.css',
    '/manifest.json',
    '/icon-192.png',
    '/icon-512.png',
    '/disclaimer.html',
];

// ── Install: precache app shell ────────────────────────────────────────────────
self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(SHELL_CACHE)
            .then(c => c.addAll(SHELL_URLS))
            .then(() => self.skipWaiting())
    );
});

// ── Activate: delete stale caches ─────────────────────────────────────────────
self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys.filter(k => !ALL_CACHES.includes(k)).map(k => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

// ── Fetch: route by request type ──────────────────────────────────────────────
self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET') return;

    const url = new URL(e.request.url);

    // API responses — network first, cached fallback when offline
    if (url.pathname.startsWith('/api/')) {
        e.respondWith(networkFirst(e.request, DATA_CACHE));
        return;
    }

    // Cross-origin images — cache first (avoids re-fetching on every scroll)
    if (url.origin !== self.location.origin && e.request.destination === 'image') {
        e.respondWith(cacheFirst(e.request, IMG_CACHE));
        return;
    }

    // App shell — cache first, network fallback
    if (url.origin === self.location.origin) {
        e.respondWith(cacheFirst(e.request, SHELL_CACHE));
        return;
    }
});

// ── Strategies ─────────────────────────────────────────────────────────────────

async function networkFirst(request, cacheName) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }
        return response;
    } catch {
        const cached = await caches.match(request);
        if (cached) return cached;
        // Return empty array so the app renders gracefully offline
        return new Response('[]', { headers: { 'Content-Type': 'application/json' } });
    }
}

async function cacheFirst(request, cacheName) {
    const cached = await caches.match(request);
    if (cached) return cached;
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }
        return response;
    } catch {
        return new Response('Offline', { status: 503 });
    }
}
