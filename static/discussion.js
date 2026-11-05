// static/discussion.js — discussion LivraPlus (texte, photo, message vocal, position).
// Utilisation : Discussion.demarrer(document.getElementById('discussion'), { urlMessages, urlEnvoyer, rapides: [...] })
(function () {
    const ROLES = { boutique: 'Boutique', livreur: 'Livreur', client: 'Client' };
    const COULEURS = { boutique: 'text-purple-700', livreur: 'text-orange-600', client: 'text-green-700' };

    function echapper(t) {
        return String(t == null ? '' : t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }
    function liens(t) {   // rend cliquables les liens http(s) d'un texte déjà échappé
        return t.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener" class="underline">$1</a>');
    }
    function duree(s) { s = Math.round(s || 0); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }

    // ----- Son d'arrivée d'un message (le navigateur exige un premier toucher sur la page) -----
    let audioCtx = null;
    function debloquerSon() { try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch (e) {} }
    ['click', 'touchstart', 'keydown'].forEach((ev) => document.addEventListener(ev, debloquerSon, { passive: true }));
    function sonner() {
        if (navigator.vibrate) navigator.vibrate([180, 90, 180]);
        if (!audioCtx) return;
        [[880, 0], [1320, 0.16]].forEach(([f, t0]) => {
            const o = audioCtx.createOscillator(), g = audioCtx.createGain(), t = audioCtx.currentTime + t0;
            o.type = 'sine'; o.frequency.value = f;
            g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.5, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
            o.connect(g).connect(audioCtx.destination); o.start(t); o.stop(t + 0.25);
        });
    }
    window.LivraPlusSon = { sonner: sonner, debloquer: debloquerSon };

    function demarrer(racine, cfg) {
        const liste = racine.querySelector('[data-liste]');
        const champ = racine.querySelector('[data-champ]');
        const etat = racine.querySelector('[data-etat]');
        const boutonEnvoyer = racine.querySelector('[data-envoyer]');
        const boutonMicro = racine.querySelector('[data-micro]');
        const boutonPhoto = racine.querySelector('[data-photo]');
        const fichierPhoto = racine.querySelector('[data-fichier-photo]');
        const boutonPosition = racine.querySelector('[data-position]');
        const barreVocal = racine.querySelector('[data-barre-vocal]');
        const minuterie = racine.querySelector('[data-minuterie]');
        let dernierId = 0, dernierJour = '', occupe = false, premierChargement = true;

        function afficherEtat(t, erreur) {
            etat.textContent = t || '';
            etat.className = 'text-xs px-3 ' + (erreur ? 'text-red-600' : 'text-gray-500');
        }

        function bulle(m) {
            let contenu = '';
            if (m.type === 'texte') contenu = '<p class="whitespace-pre-wrap break-words">' + liens(echapper(m.texte)) + '</p>';
            else if (m.type === 'photo') contenu = '<a href="' + m.media + '" target="_blank"><img src="' + m.media + '" loading="lazy" class="rounded-lg max-h-64 max-w-full"></a>'
                + (m.texte ? '<p class="mt-1 whitespace-pre-wrap break-words">' + echapper(m.texte) + '</p>' : '');
            else if (m.type === 'audio') contenu = '<div class="flex items-center gap-2"><i class="fas fa-microphone opacity-60"></i>'
                + '<audio controls preload="none" src="' + m.media + '" class="h-9 max-w-[230px]"></audio>'
                + (m.duree ? '<span class="text-xs opacity-70">' + duree(m.duree) + '</span>' : '') + '</div>';
            else if (m.type === 'position') contenu = '<a href="' + m.carte + '" target="_blank" rel="noopener" class="flex items-center gap-2 font-semibold underline">'
                + '<i class="fas fa-location-dot text-red-500"></i> Position partagée — voir sur la carte</a>';
            const role = m.role, nom = m.moi ? '' : '<p class="text-xs font-bold ' + (COULEURS[role] || '') + '">' + echapper(m.nom)
                + ' <span class="font-normal text-gray-400">· ' + (ROLES[role] || '') + '</span></p>';
            const coche = m.moi ? ' <span class="coche" data-id="' + m.id + '">' + (m.lu ? '✓✓' : '✓') + '</span>' : '';
            return '<div class="flex ' + (m.moi ? 'justify-end' : 'justify-start') + '">'
                + '<div class="max-w-[85%] rounded-2xl px-3 py-2 shadow-sm ' + (m.moi ? 'bg-purple-600 text-white rounded-br-sm' : 'bg-white text-gray-900 rounded-bl-sm border border-gray-100') + '">'
                + nom + contenu + '<p class="text-[10px] text-right mt-0.5 ' + (m.moi ? 'text-white/70' : 'text-gray-400') + '">' + m.heure + coche + '</p></div></div>';
        }

        function ajouter(messages) {
            if (!messages.length) return;
            const enBas = liste.scrollHeight - liste.scrollTop - liste.clientHeight < 80;
            const vide = liste.querySelector('[data-vide]');
            if (vide) vide.remove();
            messages.forEach((m) => {
                if (m.id <= dernierId) return;
                if (m.jour !== dernierJour) {
                    dernierJour = m.jour;
                    liste.insertAdjacentHTML('beforeend', '<p class="text-center text-[11px] text-gray-400 my-2">' + m.jour + '</p>');
                }
                liste.insertAdjacentHTML('beforeend', bulle(m));
                dernierId = m.id;
            });
            if (enBas || messages.some((m) => m.moi)) liste.scrollTop = liste.scrollHeight;
        }

        async function charger() {
            try {
                const r = await fetch(cfg.urlMessages + '?apres=' + dernierId, { cache: 'no-store' });
                if (!r.ok) return;
                const d = await r.json();
                if (!premierChargement && d.messages.some((m) => !m.moi && m.id > dernierId)) sonner();
                premierChargement = false;
                ajouter(d.messages);
                if (d.lu_jusqu_a) racine.querySelectorAll('.coche').forEach((c) => { if (+c.dataset.id <= d.lu_jusqu_a) c.textContent = '✓✓'; });
            } catch (e) { /* réseau : on réessaie au prochain tour */ }
        }

        async function envoyer(donnees, message) {
            if (occupe) return false;
            occupe = true; afficherEtat(message || 'Envoi…');
            try {
                const r = await fetch(cfg.urlEnvoyer, { method: 'POST', body: donnees, headers: { 'Accept': 'application/json' } });
                const d = await r.json().catch(() => ({}));
                if (!r.ok || !d.ok) throw new Error(d.erreur || "Le message n'est pas parti");
                ajouter([d.message]);
                afficherEtat('');
                return true;
            } catch (e) {
                afficherEtat(e.message || "Pas de connexion : le message n'est pas parti", true);
                return false;
            } finally { occupe = false; }
        }

        // ----- Texte -----
        async function envoyerTexte(texte) {
            texte = (texte || '').trim();
            if (!texte) return;
            const fd = new FormData(); fd.append('type', 'texte'); fd.append('texte', texte);
            if (await envoyer(fd)) { champ.value = ''; champ.style.height = ''; majBoutons(); }
        }
        boutonEnvoyer.addEventListener('click', () => envoyerTexte(champ.value));
        champ.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 768) { e.preventDefault(); envoyerTexte(champ.value); } });
        function majBoutons() {
            const plein = champ.value.trim().length > 0;
            boutonEnvoyer.classList.toggle('hidden', !plein); boutonMicro.classList.toggle('hidden', plein);
        }
        champ.addEventListener('input', () => { champ.style.height = 'auto'; champ.style.height = Math.min(champ.scrollHeight, 120) + 'px'; majBoutons(); });
        majBoutons();
        racine.querySelectorAll('[data-rapide]').forEach((b) => b.addEventListener('click', () => envoyerTexte(b.dataset.rapide)));

        // ----- Photo -----
        boutonPhoto.addEventListener('click', () => fichierPhoto.click());
        fichierPhoto.addEventListener('change', async () => {
            const f = fichierPhoto.files[0];
            if (!f) return;
            const fd = new FormData(); fd.append('type', 'photo'); fd.append('fichier', f); fd.append('texte', champ.value.trim());
            if (await envoyer(fd, 'Envoi de la photo…')) { champ.value = ''; majBoutons(); }
            fichierPhoto.value = '';
        });

        // ----- Position -----
        boutonPosition.addEventListener('click', () => {
            if (!navigator.geolocation) { afficherEtat('Position indisponible sur cet appareil', true); return; }
            afficherEtat('Recherche de votre position…');
            navigator.geolocation.getCurrentPosition((p) => {
                const fd = new FormData(); fd.append('type', 'position');
                fd.append('lat', p.coords.latitude); fd.append('lng', p.coords.longitude);
                envoyer(fd, 'Envoi de la position…');
            }, () => afficherEtat('Position refusée ou indisponible', true), { enableHighAccuracy: true, timeout: 20000 });
        });

        // ----- Message vocal -----
        let enregistreur = null, morceaux = [], debut = 0, minuteur = null, annule = false, flux = null;
        const aideMicro = racine.querySelector('[data-aide-micro]');
        const ua = navigator.userAgent;
        const iphone = /iPhone|iPad|iPod/.test(ua);
        const installee = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
        const appIntegree = /FBAN|FBAV|Instagram|Line\/|; wv\)|WhatsApp|musical_ly|TikTok|Snapchat/i.test(ua);
        function lienChrome() {
            return 'intent://' + location.host + location.pathname + location.search + '#Intent;scheme=https;package=com.android.chrome;end';
        }
        function montrerAide(cause) {
            let etapes;
            if (cause === 'integree') {
                etapes = '<p>Vous êtes dans le navigateur d\'une autre application (WhatsApp, Facebook, TikTok…) qui ne donne pas accès au micro.</p>'
                    + (iphone ? '<p class="mt-1">Touchez ⋯ puis <b>« Ouvrir dans Safari »</b>.</p>'
                              : '<a href="' + lienChrome() + '" class="inline-block mt-2 bg-blue-600 text-white font-semibold px-3 py-1.5 rounded-lg">Ouvrir dans Chrome</a>');
            } else if (cause === 'occupe') {
                etapes = '<p>Le micro est déjà utilisé par une autre application (appel en cours, enregistreur, WhatsApp…). Fermez-la puis réessayez.</p>';
            } else if (cause === 'absent') {
                etapes = '<p>Aucun micro trouvé sur cet appareil.</p>';
            } else if (cause === 'navigateur') {
                etapes = '<p>Ce navigateur ne permet pas d\'enregistrer. Utilisez <b>Google Chrome</b> (Android) ou <b>Safari</b> à jour (iPhone).</p>';
            } else if (iphone) {
                etapes = '<ol class="list-decimal ml-4 space-y-0.5"><li>Touchez <b>« aA »</b> à gauche de l\'adresse, puis <b>Réglages du site web</b>.</li>'
                    + '<li><b>Micro</b> → <b>Autoriser</b>.</li><li>Sinon : Réglages de l\'iPhone → Safari → Micro → Autoriser.</li><li>Revenez ici et touchez <b>Réessayer</b>.</li></ol>';
            } else if (installee) {
                etapes = '<ol class="list-decimal ml-4 space-y-0.5"><li>Ouvrez <b>Chrome</b> → menu ⋮ → <b>Paramètres</b> → <b>Paramètres des sites</b> → <b>Micro</b>.</li>'
                    + '<li>Touchez <b>' + location.host + '</b> → <b>Autoriser</b>.</li>'
                    + '<li>Vérifiez aussi : Réglages du téléphone → Applications → Chrome → Autorisations → <b>Micro : autorisé</b>.</li>'
                    + '<li>Revenez dans LivraPlus et touchez <b>Réessayer</b>.</li></ol>';
            } else {
                etapes = '<ol class="list-decimal ml-4 space-y-0.5"><li>Touchez le <b>cadenas 🔒</b> (ou ⓘ) à gauche de l\'adresse en haut.</li>'
                    + '<li><b>Autorisations</b> (ou Paramètres du site) → <b>Micro</b> → <b>Autoriser</b>.</li>'
                    + '<li>Toujours bloqué ? Réglages du téléphone → Applications → Chrome → Autorisations → <b>Micro : autorisé</b>.</li>'
                    + '<li>Revenez ici et touchez <b>Réessayer</b>.</li></ol>';
            }
            aideMicro.innerHTML = '<div class="flex items-start gap-2"><i class="fas fa-microphone-slash text-red-500 mt-0.5"></i><div class="flex-1">'
                + '<p class="font-semibold text-gray-900 mb-1">Le micro n\'est pas accessible</p>' + etapes
                + '<div class="mt-2 flex gap-2"><button type="button" data-reessayer class="bg-green-600 text-white font-semibold px-3 py-1.5 rounded-lg">Réessayer</button>'
                + '<button type="button" data-fermer-aide class="text-gray-500 px-3 py-1.5">Fermer</button></div></div></div>';
            aideMicro.classList.remove('hidden');
            aideMicro.querySelector('[data-reessayer]').addEventListener('click', () => { aideMicro.classList.add('hidden'); demarrerVocal(); });
            aideMicro.querySelector('[data-fermer-aide]').addEventListener('click', () => aideMicro.classList.add('hidden'));
            afficherEtat('');
        }
        function typeAudio() {
            const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
            return window.MediaRecorder ? types.find((t) => MediaRecorder.isTypeSupported(t)) || '' : null;
        }
        async function demarrerVocal() {
            debloquerSon();
            const type = typeAudio();
            if (appIntegree && (!navigator.mediaDevices || type === null)) { montrerAide('integree'); return; }
            if (type === null || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) { montrerAide('navigateur'); return; }
            afficherEtat('Autorisez le micro si le téléphone le demande…');
            try { flux = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
            catch (e) {
                const n = e && e.name;
                montrerAide(n === 'NotReadableError' || n === 'AbortError' ? 'occupe' : n === 'NotFoundError' || n === 'OverconstrainedError' ? 'absent'
                            : appIntegree ? 'integree' : 'refuse');
                return;
            }
            afficherEtat('');
            morceaux = []; annule = false;
            enregistreur = new MediaRecorder(flux, type ? { mimeType: type, audioBitsPerSecond: 32000 } : undefined);
            enregistreur.ondataavailable = (e) => { if (e.data.size) morceaux.push(e.data); };
            enregistreur.onstop = async () => {
                flux.getTracks().forEach((t) => t.stop());
                clearInterval(minuteur); barreVocal.classList.add('hidden');
                const secondes = (Date.now() - debut) / 1000;
                if (annule || secondes < 1) { afficherEtat(annule ? '' : 'Message trop court'); return; }
                const mime = (enregistreur.mimeType || morceaux[0]?.type || 'audio/webm');
                const blob = new Blob(morceaux, { type: mime });
                const ext = mime.includes('mp4') ? 'm4a' : mime.includes('ogg') ? 'ogg' : 'webm';
                const fd = new FormData(); fd.append('type', 'audio'); fd.append('duree', Math.round(secondes));
                fd.append('fichier', blob, 'vocal.' + ext);
                envoyer(fd, 'Envoi du message vocal…');
            };
            enregistreur.start(1000);
            debut = Date.now(); barreVocal.classList.remove('hidden'); minuterie.textContent = '0:00';
            minuteur = setInterval(() => {
                const s = (Date.now() - debut) / 1000;
                minuterie.textContent = duree(s);
                if (s >= 180) arreterVocal();
            }, 250);
        }
        function arreterVocal() { if (enregistreur && enregistreur.state !== 'inactive') enregistreur.stop(); }
        boutonMicro.addEventListener('click', () => { if (enregistreur && enregistreur.state === 'recording') arreterVocal(); else demarrerVocal(); });
        racine.querySelector('[data-vocal-envoyer]').addEventListener('click', arreterVocal);
        racine.querySelector('[data-vocal-annuler]').addEventListener('click', () => { annule = true; arreterVocal(); });

        charger().then(() => { liste.scrollTop = liste.scrollHeight; });
        setInterval(() => { if (!document.hidden) charger(); }, 4000);
        document.addEventListener('visibilitychange', () => { if (!document.hidden) charger(); });
    }

    window.Discussion = { demarrer: demarrer };
})();
