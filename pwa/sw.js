const CACHE = 'wsf-v5';
const SHELL = ['/', '/app.css', '/app.js', '/manifest.json', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    // API calls: always network only
    if (new URL(e.request.url).pathname.startsWith('/api/')) {
        e.respondWith(fetch(e.request));
        return;
    }
    // Everything else: network first, cache as offline fallback
    e.respondWith(
        fetch(e.request)
            .then(res => {
                const clone = res.clone();
                caches.open(CACHE).then(c => c.put(e.request, clone));
                return res;
            })
            .catch(() => caches.match(e.request))
    );
});
