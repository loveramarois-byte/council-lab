const CACHE_NAME = "council-mobile-v1";
const APP_ASSETS = ["/manifest.webmanifest", "/icons/council-192.png", "/icons/council-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || !new URL(event.request.url).pathname.startsWith("/icons/")) return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
