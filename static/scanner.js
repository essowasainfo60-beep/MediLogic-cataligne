// static/scanner.js — lecture d'un code-barres avec la caméra du téléphone.
//   Scanner.ouvrir(function (code) { ... })  → appelle la fonction avec le code lu, puis se ferme.
// Utilise le lecteur intégré du navigateur (Chrome Android) ; sinon charge html5-qrcode (iPhone…).
// Une douchette USB / Bluetooth n'a pas besoin de ce fichier : elle « tape » le code dans le champ, puis Entrée.
(function () {
    var FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code'];
    var fond = null, flux = null, boucle = null, lecteurSecours = null, rappel = null;

    function construire() {
        fond = document.createElement('div');
        fond.style.cssText = 'position:fixed;inset:0;z-index:80;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center';
        fond.innerHTML =
            '<div id="scanZone" style="position:relative;width:100%;max-width:520px;aspect-ratio:3/4;overflow:hidden">' +
            '  <video id="scanVideo" playsinline muted style="width:100%;height:100%;object-fit:cover"></video>' +
            '  <div id="scanSecours" style="width:100%;display:none"></div>' +
            '  <div style="position:absolute;left:10%;right:10%;top:38%;height:24%;border:3px solid #22c55e;border-radius:14px;box-shadow:0 0 0 9999px rgba(0,0,0,.45)"></div>' +
            '</div>' +
            '<p style="color:#fff;margin-top:14px;font:600 15px system-ui;text-align:center;padding:0 16px">Placez le code-barres dans le cadre vert</p>' +
            '<p id="scanErreur" style="color:#fca5a5;margin-top:6px;font:13px system-ui;text-align:center;padding:0 16px"></p>' +
            '<button type="button" id="scanFermer" style="margin-top:16px;background:#fff;color:#111;border:0;border-radius:9999px;padding:12px 28px;font:700 15px system-ui">Fermer</button>';
        document.body.appendChild(fond);
        fond.querySelector('#scanFermer').addEventListener('click', fermer);
    }
    function erreur(t) { var e = fond && fond.querySelector('#scanErreur'); if (e) e.textContent = t; }
    function lu(code) {
        if (!code) return;
        var f = rappel;
        if (navigator.vibrate) navigator.vibrate(80);
        fermer();
        if (f) f(String(code).trim());
    }
    function fermer() {
        if (boucle) { cancelAnimationFrame(boucle); boucle = null; }
        if (flux) { flux.getTracks().forEach(function (t) { t.stop(); }); flux = null; }
        if (lecteurSecours) { try { lecteurSecours.stop().catch(function () {}); } catch (e) {} lecteurSecours = null; }
        if (fond) { fond.remove(); fond = null; }
        document.body.style.overflow = '';
    }
    function charger(src) {
        return new Promise(function (ok, ko) {
            var s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = ko; document.head.appendChild(s);
        });
    }
    async function natif() {
        var formats = FORMATS;
        try { formats = (await BarcodeDetector.getSupportedFormats()).filter(function (f) { return FORMATS.indexOf(f) >= 0; }); } catch (e) {}
        var detecteur = new BarcodeDetector({ formats: formats.length ? formats : FORMATS });
        flux = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
        var video = fond.querySelector('#scanVideo');
        video.srcObject = flux;
        await video.play();
        async function tour() {
            if (!fond) return;
            try {
                var codes = await detecteur.detect(video);
                if (codes.length) return lu(codes[0].rawValue);
            } catch (e) {}
            boucle = requestAnimationFrame(tour);
        }
        tour();
    }
    async function secours() {
        fond.querySelector('#scanVideo').style.display = 'none';
        var zone = fond.querySelector('#scanSecours');
        zone.style.display = 'block';
        if (!window.Html5Qrcode) await charger('https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js');
        lecteurSecours = new Html5Qrcode('scanSecours', { verbose: false });
        await lecteurSecours.start({ facingMode: 'environment' }, { fps: 12, qrbox: { width: 260, height: 140 } },
                                   function (texte) { lu(texte); }, function () {});
    }
    window.Scanner = {
        ouvrir: async function (f) {
            rappel = f;
            construire();
            document.body.style.overflow = 'hidden';
            try {
                if ('BarcodeDetector' in window) await natif();
                else await secours();
            } catch (e) {
                erreur(e && e.name === 'NotAllowedError'
                    ? "Accès à la caméra refusé : autorisez la caméra pour ce site dans les réglages du navigateur."
                    : "Caméra indisponible sur cet appareil. Tapez le code ou utilisez une douchette.");
            }
        },
        fermer: fermer,
    };
})();
