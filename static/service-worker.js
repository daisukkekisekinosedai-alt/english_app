const CACHE_NAME = "english-pocket-natural-tts-v1";
const ASSETS = [
    "/",
    "/static/css/style.css",
    "/static/js/app.js",
    "/static/manifest.json",
    "/static/icons/icon-180.png",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png"
];

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
    );
});

self.addEventListener("fetch", event => {
    event.respondWith(
        caches.match(event.request).then(response => response || fetch(event.request))
    );
});
