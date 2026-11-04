// static/sw.js
// ============================================================
// Service worker de "LivraPlus" : condition technique pour que
// Chrome/Edge/Android proposent d'installer l'application (icône sur
// l'écran d'accueil / bouton "Installer"). Même stratégie prudente que
// GBoutik : seuls le manifeste et les icônes sont mis en cache ; les pages
// (commandes, prix, stock) passent TOUJOURS par le réseau d'abord, le cache
// ne sert qu'en dernier recours hors-ligne.
// ============================================================

const CACHE_NAME = 'livraplus-v1';
const ASSETS_STATIQUES = [
    '/app-manifest.json',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(ASSETS_STATIQUES))
            .catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cles) => Promise.all(
            cles.filter((cle) => cle !== CACHE_NAME).map((cle) => caches.delete(cle))
        ))
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const { request } = event;
    if (request.method !== 'GET') return;

    const estAssetStatique = ASSETS_STATIQUES.some((url) => request.url.endsWith(url));
    if (estAssetStatique) {
        event.respondWith(caches.match(request).then((reponse) => reponse || fetch(request)));
        return;
    }

    // Pages : réseau d'abord ; cache seulement si hors-ligne.
    event.respondWith(
        fetch(request)
            .then((reponse) => {
                if (reponse && reponse.ok && reponse.type === 'basic') {
                    const copie = reponse.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(request, copie)).catch(() => {});
                }
                return reponse;
            })
            .catch(() => caches.match(request))
    );
});

// ---------- Notifications « push » : « Votre livreur est arrivé » ----------
// Le téléphone sonne et vibre même si la page de suivi est fermée.
self.addEventListener('push', (event) => {
    let d = {};
    try { d = event.data ? event.data.json() : {}; } catch (e) { d = { corps: event.data ? event.data.text() : '' }; }
    event.waitUntil(self.registration.showNotification(d.titre || 'LivraPlus', {
        body: d.corps || '',
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-192.png',
        tag: d.tag || 'livraplus',
        renotify: true,
        requireInteraction: true,
        vibrate: [400, 150, 400, 150, 400, 150, 800],
        data: { url: d.url || '/' },
    }));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((fenetres) => {
        for (const f of fenetres) {
            if (f.url.includes(url) && 'focus' in f) { f.navigate(f.url); return f.focus(); }
        }
        return self.clients.openWindow(url);
    }));
});
