// Bahi-Khata — service worker.
//
// Deliberately small. It exists to make the app installable and to show
// something better than the browser's error page when the network is gone.
// It is not an offline-capture layer: entering expenses without a connection
// is Step 19 and needs a real queue, not a cache.
//
// Three rules it must not break:
//
//   1. Never cache a page. Every page carries a per-session CSRF token, so a
//      cached page would post a token the server rejects — the user would see
//      "your session expired" on a form that looked perfectly fine. Cached
//      balances would be quietly wrong too, which is worse than a blank page.
//   2. Never touch a non-GET request. "A GET never writes" is the invariant
//      that makes a shared quick-add link safe; the worker must not be the
//      thing that breaks it.
//   3. Never fall back to the shell for a page the user asked for. Showing a
//      stale dashboard when they wanted a fresh one is a lie about their money.

var CACHE = 'bahikhata-v1';

// Only fingerprint-free, non-authenticated assets. Everything here is either
// static or a page with no session state in it.
var PRECACHE = [
  '/offline',
  '/static/css/app.css',
  '/static/js/main.js',
  '/static/fonts/hanken-grotesk-latin.woff2',
  '/static/fonts/hanken-grotesk-latin-ext.woff2',
  '/static/fonts/bricolage-grotesque-latin.woff2',
  '/static/fonts/bricolage-grotesque-latin-ext.woff2',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE)
      // addAll is all-or-nothing: one 404 and the whole worker fails to
      // install. Add them individually so a renamed asset degrades instead.
      .then(function (cache) {
        return Promise.all(PRECACHE.map(function (url) {
          return cache.add(url).catch(function () { /* skip this one */ });
        }));
      })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys.map(function (key) {
          return key === CACHE ? null : caches.delete(key);
        }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var request = event.request;

  // Rule 2. Writes go to the network or they do not happen.
  if (request.method !== 'GET') return;

  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Rule 1 and 3. Pages always come from the network; if that fails, say so
  // plainly rather than serving yesterday's numbers.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match('/offline');
      })
    );
    return;
  }

  // Static assets: cache first. They change only on deploy, and a deploy
  // bumps CACHE, which drops the old one in activate.
  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(
      caches.match(request).then(function (hit) {
        if (hit) return hit;
        return fetch(request).then(function (response) {
          if (response && response.ok) {
            var copy = response.clone();
            caches.open(CACHE).then(function (c) { c.put(request, copy); });
          }
          return response;
        });
      })
    );
    return;
  }

  // Anything else — /healthz, future JSON — goes straight to the network.
});
