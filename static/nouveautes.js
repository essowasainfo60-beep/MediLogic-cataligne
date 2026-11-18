// static/nouveautes.js — le client s'abonne (ou se désabonne) aux nouveautés d'une boutique.
// Chaque bloc [data-nouveautes] porte ses adresses : data-abonner, data-desabonner, data-etat, data-cle.
(function () {
    var POSSIBLE = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    var IPHONE = /iPhone|iPad|iPod/i.test(navigator.userAgent);
    var INSTALLEE = window.navigator.standalone || (window.matchMedia && matchMedia('(display-mode: standalone)').matches);

    function cle(b64) {
        var s = (b64 + '='.repeat((4 - b64.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/');
        return Uint8Array.from(atob(s), function (c) { return c.charCodeAt(0); });
    }
    function enTexte(o) { return Array.from(new Uint8Array(o)).join(','); }
    function poster(url, donnees) {
        return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(donnees) })
            .then(function (r) { if (!r.ok) throw new Error('refus'); return r.json(); });
    }
    async function abonnementActuel() {
        var reg = await navigator.serviceWorker.getRegistration('/');
        return reg ? reg.pushManager.getSubscription() : null;
    }
    async function abonnement(CLE, demander) {
        if (Notification.permission !== 'granted') {
            if (!demander || await Notification.requestPermission() !== 'granted') return null;
        }
        var reg = await navigator.serviceWorker.register('/sw.js');
        await navigator.serviceWorker.ready;
        var abo = await reg.pushManager.getSubscription();
        var k = abo && abo.options && abo.options.applicationServerKey;
        if (abo && k && enTexte(k) !== enTexte(cle(CLE))) { await abo.unsubscribe(); abo = null; }
        return abo || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: cle(CLE) });
    }

    window.Nouveautes = {
        possible: POSSIBLE,
        // Abonnement push de ce téléphone (null si refusé / impossible) — sert aussi aux demandes d'articles épuisés
        abonnementPush: function (CLE, demander) {
            if (!POSSIBLE || !CLE) return Promise.resolve(null);
            return abonnement(CLE, demander).then(function (a) { return a ? a.toJSON() : null; }).catch(function () { return null; });
        },
        // Abonne ce téléphone (appelé aussi par la page de suivi avec l'alerte d'arrivée)
        abonner: async function (urlAbonner, CLE, demander) {
            var abo = await abonnement(CLE, demander);
            if (!abo) return false;
            return (await poster(urlAbonner, abo)).ok;
        },
        brancher: function (bloc) {
            var d = bloc.dataset, bouton = bloc.querySelector('[data-nouv-btn]'), texte = bloc.querySelector('[data-nouv-texte]');
            var titre = bloc.querySelector('[data-nouv-titre]');
            var texteInitial = texte.innerHTML;
            function afficher(abonne) {
                bloc.classList.toggle('nouv-actif', abonne);
                titre.textContent = abonne ? '✓ Vous serez prévenu des nouveautés' : '🔔 Être prévenu des nouveautés';
                texte.innerHTML = abonne ? 'Une notification quand la boutique ajoute des articles (au plus 1 par jour).' : texteInitial;
                bouton.textContent = abonne ? 'Arrêter' : 'Activer';
                bouton.dataset.abonne = abonne ? '1' : '';
            }
            if (!POSSIBLE) {
                if (IPHONE && !INSTALLEE) {
                    texte.innerHTML = "Sur iPhone : touchez <b>Partager</b> puis <b>« Sur l'écran d'accueil »</b>, ouvrez la boutique depuis cette icône, puis activez.";
                    bouton.classList.add('hidden');
                } else { bloc.classList.add('hidden'); }
                return;
            }
            // Déjà abonné sur ce téléphone ?
            if (Notification.permission === 'granted') {
                abonnementActuel().then(function (abo) {
                    if (!abo) return;
                    return poster(d.etat, { endpoint: abo.endpoint }).then(function (r) { afficher(!!r.abonne); });
                }).catch(function () {});
            }
            if (Notification.permission === 'denied') {
                texte.innerHTML = "Les notifications sont bloquées sur ce navigateur. Touchez l'icône à gauche de l'adresse → <b>Notifications</b> → <b>Autoriser</b>.";
            }
            bouton.addEventListener('click', async function () {
                bouton.disabled = true;
                try {
                    if (bouton.dataset.abonne) {
                        var abo = await abonnementActuel();
                        if (abo) await poster(d.desabonner, { endpoint: abo.endpoint });
                        afficher(false);
                        texte.textContent = "C'est noté : vous ne recevrez plus les nouveautés.";
                    } else {
                        bouton.textContent = 'Activation…';
                        var ok = await window.Nouveautes.abonner(d.abonner, d.cle, true);
                        if (ok) afficher(true);
                        else { bouton.textContent = 'Activer'; texte.textContent = 'Notifications refusées : vous pourrez réessayer plus tard.'; }
                    }
                } catch (e) {
                    bouton.textContent = 'Activer';
                    texte.textContent = "Impossible d'activer sur ce téléphone pour le moment.";
                } finally { bouton.disabled = false; }
            });
        },
    };
    document.querySelectorAll('[data-nouveautes]').forEach(function (b) { window.Nouveautes.brancher(b); });
})();
