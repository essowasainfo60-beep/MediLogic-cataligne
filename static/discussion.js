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
        let dernierId = 0, dernierJour = '', occupe = false;

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
        function typeAudio() {
            const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
            return window.MediaRecorder ? types.find((t) => MediaRecorder.isTypeSupported(t)) || '' : null;
        }
        async function demarrerVocal() {
            const type = typeAudio();
            if (type === null || !navigator.mediaDevices) { afficherEtat('Les messages vocaux ne marchent pas sur ce navigateur. Essayez Chrome.', true); return; }
            try { flux = await navigator.mediaDevices.getUserMedia({ audio: true }); }
            catch (e) { afficherEtat('Micro refusé : autorisez le micro pour ce site dans les réglages du navigateur.', true); return; }
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
