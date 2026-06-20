// InBack Service Worker v3.4
const CACHE_VERSION = 'v3.4';
const STATIC_CACHE = 'inback-static-' + CACHE_VERSION;
const DYNAMIC_CACHE = 'inback-dynamic-' + CACHE_VERSION;
const IMAGE_CACHE = 'inback-images-' + CACHE_VERSION;
const OFFLINE_URL = '/offline';

const STATIC_ASSETS = [
  '/offline',
  '/static/css/styles.css',
  '/static/js/main.js',
  '/static/js/comparison.js',
  '/static/images/icons/icon-192x192.png',
  '/static/images/icons/icon-512x512.png',
  '/static/images/logo.svg',
  '/manifest.json'
];

// ── INSTALL ──────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(STATIC_ASSETS.map(url => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
      .catch(err => console.warn('[SW] Install cache error (non-fatal):', err))
  );
});

// ── ACTIVATE ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  const allowed = [STATIC_CACHE, DYNAMIC_CACHE, IMAGE_CACHE];
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => !allowed.includes(k)).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── FETCH ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip: non-GET, cross-origin API calls, admin/manager routes, auth
  if (request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/admin/')) return;
  if (url.pathname.startsWith('/manager/')) return;
  if (url.pathname.includes('/login') || url.pathname.includes('/logout')) return;
  if (!url.origin.includes(self.location.origin) && !url.hostname.includes('fonts.g')) return;

  // Images: cache-first (long TTL)
  if (request.destination === 'image' || url.pathname.match(/\.(jpg|jpeg|png|gif|webp|svg|ico)$/i)) {
    event.respondWith(cacheFirst(request, IMAGE_CACHE));
    return;
  }

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // HTML pages: network-first, fallback offline
  if (request.headers.get('Accept')?.includes('text/html')) {
    event.respondWith(networkFirstWithOffline(request));
    return;
  }

  // Fonts: stale-while-revalidate
  if (url.hostname.includes('fonts.g') || url.hostname.includes('fonts.googleapis')) {
    event.respondWith(staleWhileRevalidate(request, STATIC_CACHE));
    return;
  }
});

// ── STRATEGIES ───────────────────────────────────────────────────────────────
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
    return caches.match(OFFLINE_URL) || new Response('Offline', { status: 503 });
  }
}

async function networkFirstWithOffline(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return caches.match(OFFLINE_URL) || new Response('<h1>Нет соединения</h1>', {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' }
    });
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request).then(response => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => {});
  return cached || fetchPromise;
}

// ── PUSH NOTIFICATIONS ───────────────────────────────────────────────────────
self.addEventListener('push', event => {
  if (!event.data) return;
  let data;
  try { data = event.data.json(); } catch { data = { title: 'InBack', body: event.data.text() }; }

  const options = {
    body: data.body || '',
    icon: '/static/images/icons/icon-192x192.png',
    badge: '/static/images/icons/icon-72x72.png',
    image: data.image || undefined,
    tag: data.tag || 'inback-notification',
    renotify: true,
    requireInteraction: data.requireInteraction || false,
    data: { url: data.url || '/', ...data.data },
    actions: data.actions || []
  };

  event.waitUntil(self.registration.showNotification(data.title || 'InBack', options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      for (const client of clientList) {
        if (client.url === targetUrl && 'focus' in client) return client.focus();
      }
      return clients.openWindow(targetUrl);
    })
  );
});

// ── BACKGROUND SYNC ──────────────────────────────────────────────────────────
self.addEventListener('sync', event => {
  if (event.tag === 'background-sync' || event.tag === 'inback-forms') {
    event.waitUntil(doBackgroundSync());
  }
});

/* Open (or create) the offline-queue IndexedDB */
function openSyncDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('inback-sync-db', 1);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('pending-requests')) {
        db.createObjectStore('pending-requests', { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror  = e => reject(e.target.error);
  });
}

function getAllPending(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pending-requests', 'readonly');
    const req = tx.objectStore('pending-requests').getAll();
    req.onsuccess = e => resolve(e.target.result);
    req.onerror   = e => reject(e.target.error);
  });
}

function deletePending(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pending-requests', 'readwrite');
    const req = tx.objectStore('pending-requests').delete(id);
    req.onsuccess = () => resolve();
    req.onerror   = e => reject(e.target.error);
  });
}

async function doBackgroundSync() {
  console.log('[SW] Background sync — retrying offline form submissions');
  let db;
  try { db = await openSyncDB(); } catch (e) { return; }

  const pending = await getAllPending(db);
  if (!pending.length) return;

  const results = await Promise.allSettled(pending.map(async item => {
    try {
      const resp = await fetch(item.url, {
        method: item.method || 'POST',
        headers: item.headers || { 'Content-Type': 'application/json' },
        body: item.body,
        credentials: 'same-origin'
      });
      if (resp.ok) {
        await deletePending(db, item.id);
        console.log('[SW] Replayed offline request →', item.url);
      }
    } catch (err) {
      console.warn('[SW] Retry failed (will try again):', item.url, err);
    }
  }));
  console.log('[SW] Background sync done:', results.length, 'items processed');
}

// ── MESSAGES ─────────────────────────────────────────────────────────────────
self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
  if (event.data?.type === 'GET_VERSION') {
    event.ports[0]?.postMessage({ version: CACHE_VERSION });
  }
  /* Client queues a failed request for background sync retry */
  if (event.data?.type === 'QUEUE_REQUEST' && event.data.request) {
    openSyncDB().then(db => {
      const tx = db.transaction('pending-requests', 'readwrite');
      tx.objectStore('pending-requests').add({
        ...event.data.request,
        queued_at: Date.now()
      });
    }).catch(() => {});
  }
});
