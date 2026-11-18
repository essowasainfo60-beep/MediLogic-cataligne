// static/video_article.js — envoi de la vidéo d'un article (avant l'enregistrement du formulaire)
(function () {
    var bloc = document.getElementById('blocVideo');
    if (!bloc) return;
    var DUREE_MAX = 30, TAILLE_MAX = 30 * 1024 * 1024;
    var input = document.getElementById('videoInput'), champ = document.getElementById('videoId');
    var progres = document.getElementById('videoProgres'), barre = document.getElementById('videoBarre');
    var texte = document.getElementById('videoTexte'), apercu = document.getElementById('videoApercu');
    var form = bloc.closest('form'), bouton = form && form.querySelector('[type="submit"]');
    var enCours = false;

    function message(t, erreur) {
        progres.classList.remove('hidden');
        texte.textContent = t;
        texte.className = 'text-xs mt-1 ' + (erreur ? 'text-red-600 font-semibold' : 'text-gray-600');
    }
    function bloquer(oui) {
        enCours = oui;
        if (bouton) { bouton.disabled = oui; bouton.classList.toggle('opacity-50', oui); }
    }
    function duree(fichier) {
        return new Promise(function (ok) {
            var v = document.createElement('video');
            v.preload = 'metadata';
            v.onloadedmetadata = function () { URL.revokeObjectURL(v.src); ok(v.duration); };
            v.onerror = function () { ok(null); };          // format non lu par ce navigateur : le serveur vérifiera
            v.src = URL.createObjectURL(fichier);
        });
    }
    input.addEventListener('change', async function () {
        var f = input.files[0];
        champ.value = '';
        apercu.classList.add('hidden');
        if (!f) return;
        if (f.size > TAILLE_MAX) { message('Vidéo trop lourde (' + Math.round(f.size / 1048576) + ' Mo, 30 Mo au plus) : filmez moins longtemps ou en 720p.', true); input.value = ''; return; }
        var d = await duree(f);
        if (d && d > DUREE_MAX + 1) { message('Vidéo trop longue (' + Math.round(d) + ' s) : ' + DUREE_MAX + ' secondes au plus. Coupez-la dans la galerie du téléphone.', true); input.value = ''; return; }
        var fd = new FormData();
        fd.append('video', f);
        if (d) fd.append('duree', d);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', bloc.dataset.url);
        var jeton = document.querySelector('meta[name="csrf-token"]');
        if (jeton) xhr.setRequestHeader('X-CSRFToken', jeton.content);
        xhr.setRequestHeader('Accept', 'application/json');
        xhr.upload.onprogress = function (e) {
            if (!e.lengthComputable) return;
            var p = Math.round(e.loaded / e.total * 100);
            barre.style.width = p + '%';
            message('Envoi de la vidéo… ' + p + ' % (gardez la page ouverte)');
        };
        xhr.onload = function () {
            bloquer(false);
            var r = {};
            try { r = JSON.parse(xhr.responseText); } catch (e) {}
            if (xhr.status === 200 && r.success) {
                champ.value = r.id;
                barre.style.width = '100%';
                message('✓ Vidéo prête (' + (r.taille / 1048576).toFixed(1) + ' Mo). Enregistrez l\'article pour la publier.');
                apercu.src = URL.createObjectURL(f);
                apercu.classList.remove('hidden');
                var actuelle = document.getElementById('videoActuelle');
                if (actuelle) actuelle.classList.add('opacity-40');
            } else {
                message(r.message || (xhr.status === 413 ? 'Vidéo trop lourde' : "Échec de l'envoi : réessayez (connexion ?)"), true);
                input.value = '';
            }
        };
        xhr.onerror = function () { bloquer(false); message("Échec de l'envoi : vérifiez la connexion et réessayez.", true); input.value = ''; };
        bloquer(true);
        barre.style.width = '0%';
        message('Envoi de la vidéo… 0 %');
        xhr.send(fd);
    });
    if (form) form.addEventListener('submit', function (e) {
        if (enCours) { e.preventDefault(); e.stopImmediatePropagation(); alert('Attendez la fin de l\'envoi de la vidéo.'); }
    }, true);
})();
