// static/carte.js — petites aides pour les cartes LivraPlus (Leaflet + OpenStreetMap, gratuit).
// Nécessite Leaflet chargé avant ce fichier (voir templates/_carte.html).
(function () {
    function icone(emoji, fond) {
        return L.divIcon({
            className: '',
            html: '<div style="background:' + fond + ';width:38px;height:38px;border-radius:50%;display:flex;align-items:center;' +
                  'justify-content:center;font-size:20px;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.35)">' + emoji + '</div>',
            iconSize: [38, 38], iconAnchor: [19, 19], popupAnchor: [0, -18],
        });
    }

    window.Carte = {
        LOME: [6.1375, 1.2123],
        livreur: function () { return icone('🛵', '#7c3aed'); },
        client: function () { return icone('🏠', '#16a34a'); },
        depart: function () { return icone('🏁', '#0b1d35'); },

        creer: function (element, centre, zoom) {
            var carte = L.map(element, { zoomControl: true, attributionControl: true, scrollWheelZoom: false }).setView(centre || Carte.LOME, zoom || 13);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19, attribution: '&copy; OpenStreetMap',
            }).addTo(carte);
            return carte;
        },

        // Cadre la carte pour voir tous les points donnés ([[lat,lng], …])
        cadrer: function (carte, points, zoomMax) {
            var valides = points.filter(function (p) { return p && p[0] != null && p[1] != null; });
            if (valides.length === 1) carte.setView(valides[0], zoomMax || 15);
            else if (valides.length > 1) carte.fitBounds(valides, { padding: [40, 40], maxZoom: zoomMax || 16 });
        },

        ilYa: function (secondes) {
            if (secondes == null) return '';
            if (secondes < 60) return "à l'instant";
            if (secondes < 3600) return 'il y a ' + Math.round(secondes / 60) + ' min';
            return 'il y a ' + Math.round(secondes / 3600) + ' h';
        },

        echapper: function (t) {
            return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
            });
        },
    };
})();
