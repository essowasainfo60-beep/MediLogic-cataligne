// static/sw.js
// ============================================================
// Service worker de "CTL Catalogue" : condition technique pour que
// Chrome/Edge/Android proposent d'installer l'application (icône sur
// l'écran d'accueil / bouton "Installer"). Même stratégie prudente que
// GBoutik : seuls le manifeste et les icônes sont mis en cache ; les pages
// (commandes, prix, stock) passent TOUJOURS par le réseau d'abord, le cache
// ne sert qu'en dernier recours hors-ligne.
// ============================================================

const CACHE_NAME = 'ctl-catalogue-v1';
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
