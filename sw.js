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
    e.respondWith(fetch(e.request));
});
