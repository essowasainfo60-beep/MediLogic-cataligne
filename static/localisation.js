// static/localisation.js — trouver la position du client, de façon fiable.
//  - Localisation.trouver() : écoute le GPS jusqu'à 25 s et garde la position la plus précise
//    (le premier point est souvent imprécis, le GPS s'affine en quelques secondes) ;
//  - Localisation.surCarte() : le client place lui-même sa maison sur une carte
//    (marche toujours : GPS coupé, refusé, navigateur de WhatsApp, intérieur d'un bâtiment…) ;
//  - Localisation.aide(cause) : explications claires selon le téléphone.
(function () {
    var UA = navigator.userAgent;
    var IPHONE = /iPhone|iPad|iPod/i.test(UA) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    var INTEGREE = /FBAN|FBAV|FB_IAB|Instagram|WhatsApp|TikTok|musical_ly|Snapchat|Line\//i.test(UA);
    var LOME = [6.1375, 1.2123];

    function chargerLeaflet() {
        if (window.L) return Promise.resolve();
        return new Promise(function (ok, ko) {
            var css = document.createElement('link');
            css.rel = 'stylesheet';
            css.href = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';
            document.head.appendChild(css);
            var js = document.createElement('script');
            js.src = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
            js.onload = function () { ok(); };
            js.onerror = function () { ko(new Error('carte')); };
            document.head.appendChild(js);
        });
    }

    window.Localisation = {
        integree: INTEGREE,

        trouver: function (dureeMax) {
            dureeMax = dureeMax || 25000;
            return new Promise(function (ok, ko) {
                if (!navigator.geolocation) { ko({ cause: 'navigateur' }); return; }
                if (!window.isSecureContext) { ko({ cause: 'navigateur' }); return; }
                var meilleure = null, fini = false, dernierCode = null, id = null;
                function terminer() {
                    if (fini) return;
                    fini = true;
                    if (id !== null) navigator.geolocation.clearWatch(id);
                    clearTimeout(minuterie);
                    if (meilleure) ok(meilleure);
                    else ko({ cause: dernierCode === 1 ? 'refuse' : dernierCode === 2 ? 'gps' : 'delai' });
                }
                var minuterie = setTimeout(terminer, dureeMax);
                function recu(p) {
                    var pos = { lat: p.coords.latitude, lng: p.coords.longitude, precision: Math.round(p.coords.accuracy || 9999) };
                    if (!meilleure || pos.precision < meilleure.precision) meilleure = pos;
                    if (meilleure.precision <= 40) terminer();      // assez précis : inutile d'attendre
                }
                function erreur(e) {
                    dernierCode = e && e.code;
                    if (dernierCode === 1) { terminer(); return; }  // refusé : on arrête tout de suite
                }
                try {
                    id = navigator.geolocation.watchPosition(recu, erreur, { enableHighAccuracy: true, maximumAge: 0, timeout: dureeMax });
                    // En parallèle, une position rapide (réseau) au cas où le GPS ne répond pas
                    navigator.geolocation.getCurrentPosition(recu, function () {}, { enableHighAccuracy: false, maximumAge: 120000, timeout: 10000 });
                } catch (e) { ko({ cause: 'navigateur' }); }
            });
        },

        aide: function (cause) {
            if (cause === 'refuse' && INTEGREE) {
                return "Le navigateur de WhatsApp / Facebook / TikTok bloque la localisation. " +
                       "Touchez <b>« Placer sur la carte »</b> ci-dessous : c'est aussi précis.";
            }
            if (cause === 'refuse') {
                return IPHONE
                    ? "Localisation refusée. Réglages de l'iPhone → <b>Confidentialité</b> → <b>Service de localisation</b> → <b>Safari</b> → « Lorsque l'app est active ». " +
                      "Ou plus simple : <b>placez votre position sur la carte</b>."
                    : "Localisation refusée. Touchez l'icône à gauche de l'adresse (🔒 ou ⓘ) → <b>Autorisations</b> → <b>Position</b> → Autoriser. " +
                      "Ou plus simple : <b>placez votre position sur la carte</b>.";
            }
            if (cause === 'gps') {
                return "Le GPS du téléphone semble coupé : ouvrez le volet du haut de l'écran et activez <b>Localisation / Position</b>, puis réessayez. " +
                       "Ou <b>placez votre position sur la carte</b>.";
            }
            if (cause === 'delai') {
                return "Le GPS n'a pas répondu à temps (souvent à l'intérieur). Approchez-vous d'une fenêtre et réessayez, " +
                       "ou <b>placez votre position sur la carte</b>.";
            }
            if (cause === 'imprecis') {
                return "Le téléphone ne donne qu'une position approximative. <b>Placez votre maison sur la carte</b> pour que le livreur vous trouve.";
            }
            return "Ce navigateur ne donne pas la position. <b>Placez votre position sur la carte</b>.";
        },

        // Carte plein écran : le client déplace la carte sous l'épingle, puis valide.
        surCarte: function (depart) {
            return chargerLeaflet().then(function () {
                return new Promise(function (ok, ko) {
                    var fond = document.createElement('div');
                    fond.style.cssText = 'position:fixed;inset:0;z-index:1000;background:#fff;display:flex;flex-direction:column';
                    fond.innerHTML =
                        '<div style="padding:10px 12px;background:#0b1d35;color:#fff;font:600 15px Arial">📍 Déplacez la carte pour mettre l\'épingle sur votre maison' +
                        '<div style="font:400 12px Arial;opacity:.75;margin-top:2px">Zoomez avec deux doigts. Touchez la carte pour y mettre l\'épingle.</div></div>' +
                        '<div style="position:relative;flex:1"><div class="lp-carte" style="position:absolute;inset:0"></div>' +
                        '<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-100%);font-size:40px;z-index:500;pointer-events:none;filter:drop-shadow(0 2px 3px rgba(0,0,0,.4))">📍</div></div>' +
                        '<div style="display:flex;gap:8px;padding:10px;background:#f3f4f6">' +
                        '<button type="button" data-annuler style="padding:12px 16px;border-radius:12px;background:#e5e7eb;font:600 15px Arial">Annuler</button>' +
                        '<button type="button" data-valider style="flex:1;padding:12px;border-radius:12px;background:#16a34a;color:#fff;font:700 16px Arial">✅ C\'est ici</button></div>';
                    document.body.appendChild(fond);
                    var centre = depart && depart.lat != null ? [depart.lat, depart.lng] : LOME;
                    var carte = L.map(fond.querySelector('.lp-carte'), { zoomControl: true }).setView(centre, depart ? 17 : 13);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap' }).addTo(carte);
                    carte.on('click', function (e) { carte.panTo(e.latlng); });
                    setTimeout(function () { carte.invalidateSize(); }, 100);
                    function fermer() { carte.remove(); fond.remove(); }
                    fond.querySelector('[data-annuler]').onclick = function () { fermer(); ko({ cause: 'annule' }); };
                    fond.querySelector('[data-valider]').onclick = function () {
                        if (carte.getZoom() < 15) {
                            alert('Zoomez davantage pour placer précisément votre maison (au moins jusqu\'à voir les rues).');
                            return;
                        }
                        var c = carte.getCenter();
                        fermer();
                        ok({ lat: c.lat, lng: c.lng, precision: carte.getZoom() >= 17 ? 20 : 60, carte: true });
                    };
                });
            });
        },
    };
})();
