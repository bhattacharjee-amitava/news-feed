// No caching — every request goes straight to network.
// Service worker kept only for PWA install eligibility.

self.addEventListener('install',  () => self.skipWaiting());
self.addEventListener('activate', e => {
    // Delete all old caches
    e.waitUntil(
        caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))))
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    // Force bypass of HTTP cache for all same-origin GET requests
    const url = new URL(e.request.url);
    if (e.request.method === 'GET' && url.origin === self.location.origin) {
        e.respondWith(fetch(e.request, { cache: 'no-store' }));
    } else {
        e.respondWith(fetch(e.request));
    }
});
