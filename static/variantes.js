// static/variantes.js — choix d'une variante (pointure, couleur…) par le client ou la boutique.
// Les valeurs épuisées sont grisées selon ce qui est déjà choisi : si la pointure 24
// n'existe plus en rouge, « Rouge » est barré dès que l'on choisit 24 (et inversement).
//
//   Variantes.brancher(conteneur, donnees, rappel)
//     conteneur : élément qui contient les <select data-option="Pointure">…
//     donnees   : { options, suivi, prix, v: { cle: { s: stock, p: prix } }, photos }
//     rappel    : appelé à chaque changement avec { complet, cle, choisis, prix, stock }
(function () {
    function cleDe(choisis) {
        return Object.keys(choisis).sort().map(function (o) { return o + '=' + choisis[o]; }).join('|');
    }
    function possible(d, partiel) {
        if (!d.suivi) return true;
        var morceaux = Object.keys(partiel).map(function (o) { return o + '=' + partiel[o]; });
        return Object.keys(d.v).some(function (cle) {
            if (!((d.v[cle] || {}).s > 0)) return false;
            var parts = cle.split('|');
            return morceaux.every(function (m) { return parts.indexOf(m) >= 0; });
        });
    }
    window.Variantes = {
        cle: cleDe,
        possible: possible,
        brancher: function (conteneur, d, rappel) {
            var selects = Array.prototype.slice.call(conteneur.querySelectorAll('select[data-option]'));
            function choisis() {
                var c = {};
                selects.forEach(function (s) { if (s.value) c[s.dataset.option] = s.value; });
                return c;
            }
            function maj() {
                var c = choisis();
                selects.forEach(function (s) {
                    var o = s.dataset.option;
                    Array.prototype.forEach.call(s.options, function (opt) {
                        if (!opt.value) return;
                        var partiel = Object.assign({}, c);
                        partiel[o] = opt.value;
                        // Seuls les AUTRES choix déjà faits comptent pour griser cette valeur
                        var autres = Object.assign({}, partiel);
                        var ok = possible(d, autres);
                        opt.textContent = opt.value + (ok ? '' : ' — épuisé');
                        opt.style.color = ok ? '' : '#9ca3af';
                    });
                });
                var complet = selects.length > 0 && selects.every(function (s) { return s.value; });
                var cle = complet ? cleDe(c) : null;
                var x = cle ? (d.v[cle] || {}) : null;
                rappel({
                    complet: complet, cle: cle, choisis: c,
                    prix: x && x.p != null ? x.p : d.prix,
                    stock: d.suivi && x ? (x.s || 0) : null,
                });
            }
            selects.forEach(function (s) { s.addEventListener('change', maj); });
            maj();
            return { maj: maj };
        },
    };
})();
