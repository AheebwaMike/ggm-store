// Bump this number on every release that changes cached assets (CSS, JS, icons).
// The activate step below deletes every cache that doesn't match, so returning
// users get the new files instead of the old ones.
const CACHE_NAME = 'ggm-store-v3';
const PRECACHE_URLS = [
  '/',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache or serve these from the cache: they show live, per-customer state.
  // '/cart' also covers /cart/count/ and /cart/bar/.
  const excludedPaths = [
    '/staff',
    '/cart',
    '/admin',
    '/checkout',
    '/order',
    '/orders',
    '/my-orders',
    '/login',
    '/logout',
    '/a/',          // apartment QR links must always reach the server so scans are counted
  ];
  if (excludedPaths.some((path) => url.pathname.startsWith(path))) return;

  // Static files: cache-first. The full URL (including ?v=N) is the cache key,
  // so changing the ?v= number in base.html always fetches a fresh copy.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      }))
    );
    return;
  }

  // Everything else: network-first, falling back to the cache when offline.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = {
      title: 'GGM Store',
      body: event.data ? event.data.text() : '',
    };
  }

  const options = {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    vibrate: [200, 100, 200, 100, 200],
    requireInteraction: true,
    silent: false,
    data: {
      url: data.url || '/',
    },
  };
  event.waitUntil(
    self.registration.showNotification(data.title || 'GGM Store', options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    let target;
    try {
      target = new URL(event.notification.data?.url || '/', self.location.origin);
      if (target.origin !== self.location.origin) target = new URL('/', self.location.origin);
    } catch (error) {
      target = new URL('/', self.location.origin);
    }

    const windowClients = await clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    });
    for (const client of windowClients) {
      if (client.url === target.href && 'focus' in client) {
        return client.focus();
      }
    }
    return clients.openWindow ? clients.openWindow(target.href) : undefined;
  })());
});