import hashlib
from datetime import datetime
from urllib.parse import quote

from flask import (Blueprint, Response, abort, after_this_request, flash, jsonify, redirect,
                   render_template, request, session, url_for)

import caisse
import messages_whatsapp as msg
from zones_detection import zone_pour_adresse, index_quartiers
from creneaux import creneaux_disponibles
import promos
import notifications
import suivi_gps
from utils import enregistrer_photo
import stock
from models import db, Boutique, Article, Commande, Photo, Zone, Livreur, enregistrer_avec_numero

client_bp = Blueprint('client', __name__)


def nombre_articles(panier):
    return sum(item['quantite'] for item in panier.values())


def lire_coordonnee(valeur, limite):
    try:
        v = float(valeur)
        return v if -limite <= v <= limite else None
    except (TypeError, ValueError):
        return None


def boutique_du_panier(panier):
    for item in panier.values():
        return db.session.get(Boutique, item.get('boutique_id'))
    return None


@client_bp.app_context_processor
def injecter_panier():
    return {'panier_quantite': nombre_articles(session.get('panier', {}))}

# ==================== PHOTOS (stockées dans la base Neon) ====================

@client_bp.route('/photo/<int:photo_id>')
def photo(photo_id):
    photo = db.session.get(Photo, photo_id)
    if not photo:
        abort(404)
    reponse = Response(photo.donnees, mimetype=photo.mime)
    # Une photo n'est jamais modifiée (une nouvelle = un nouvel id) : cache long
    reponse.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return reponse

# ==================== ACCUEIL & SELECTION BOUTIQUE ====================

def boutique_visitee():
    """Boutique dont le client a ouvert le lien secret (sinon None)."""
    boutique_id = session.get('last_boutique_id')
    boutique = db.session.get(Boutique, boutique_id) if boutique_id else None
    return boutique if boutique and boutique.active else None


@client_bp.route('/')
def accueil():
    # Un client ne revient que vers la boutique dont il a reçu le lien.
    # Jamais de redirection vers « une boutique au hasard » : sans lien, pas de catalogue.
    boutique = boutique_visitee()
    if boutique:
        return redirect(url_for('client.catalogue', code=boutique.lien_public))
    return redirect(url_for('boutique.connexion'))

@client_bp.route('/c/<code>')
def catalogue(code):
    boutique = Boutique.query.filter_by(lien_public=code).first()
    if not boutique or not boutique.active:
        session.pop('last_boutique_id', None)
        return render_template('client/lien_invalide.html'), 404

    session['last_boutique_id'] = boutique.id
    boutique_id = boutique.id
    from datetime import date
    promos_affichees = [p for p in boutique.codes_promo if p.actif and p.affiche
                        and (not p.date_fin or p.date_fin >= date.today())
                        and (not p.utilisations_max or p.utilisations < p.utilisations_max)]
    articles = (Article.query.filter_by(boutique_id=boutique_id, archive=False)
                .order_by(Article.created_at.desc()).all())

    mes_commandes = commandes_du_telephone(boutique)
    en_cours = [c for c in mes_commandes if c.statut in ('nouvelle', 'confirmee', 'en_livraison', 'echec')]
    return render_template('client/catalogue.html',
                           mes_commandes=mes_commandes, en_cours=en_cours,
                           promos_affichees=promos_affichees,
                           boutique=boutique,
                           articles=articles,
                           panier=session.get('panier', {}))

# ==================== GESTION DU PANIER ====================

@client_bp.route('/ajouter_panier', methods=['POST'])
def ajouter_panier():
    article = Article.query.get_or_404(request.form.get('article_id', type=int))
    quantite = max(1, min(request.form.get('quantite', 1, type=int) or 1, 999))
    veut_json = request.accept_mimetypes.best == 'application/json'

    # On ne commande que dans la boutique dont on a ouvert le lien
    visitee = boutique_visitee()
    epuise = article.stock is not None and article.stock <= 0
    if article.archive or epuise or not visitee or article.boutique_id != visitee.id:
        if veut_json:
            return jsonify(success=False, message='Article épuisé' if epuise else 'Article indisponible'), 400
        flash('Article indisponible', 'danger')
        return redirect(url_for('client.accueil'))

    panier = session.get('panier', {})
    # Un panier = une seule boutique (une commande part vers un seul WhatsApp)
    if any(item.get('boutique_id') != article.boutique_id for item in panier.values()):
        panier = {}

    # Choix du client (taille, couleur…) : chaque combinaison est une ligne du panier
    try:
        choix = article.lire_choix({o: request.form.get(f'option_{o}') for o in (article.options or {})})
    except ValueError as e:
        if veut_json:
            return jsonify(success=False, message=str(e)), 400
        flash(str(e), 'danger')
        return redirect(url_for('client.catalogue', code=visitee.lien_public))
    cle = str(article.id) + (('-' + hashlib.md5(choix.encode()).hexdigest()[:8]) if choix else '')
    if cle in panier:
        panier[cle]['quantite'] += quantite
    else:
        panier[cle] = {
            'nom': article.nom + (f' ({choix})' if choix else ''),
            'options': choix or None,
            'prix': article.prix,
            'quantite': quantite,
            'boutique_id': article.boutique_id,
            'article_id': article.id,
            'numero': article.numero,
            'photo': (article.photos_urls or [None])[0],
        }

    session['panier'] = panier
    session.modified = True

    if veut_json:
        return jsonify(success=True, panier_count=nombre_articles(panier))
    flash(f'{article.nom} ajouté au panier', 'success')
    return redirect(url_for('client.catalogue', code=visitee.lien_public))

@client_bp.route('/panier')
def voir_panier():
    panier = session.get('panier', {})
    total = sum(item['prix'] * item['quantite'] for item in panier.values())
    boutique = boutique_du_panier(panier)
    if not boutique and session.get('last_boutique_id'):
        boutique = db.session.get(Boutique, session['last_boutique_id'])

    return render_template('client/panier.html', panier=panier, total=total, boutique=boutique)

@client_bp.route('/modifier_quantite/<cle>', methods=['POST'])
def modifier_quantite(cle):
    panier = session.get('panier', {})
    if cle in panier:
        quantite = request.form.get('quantite', 1, type=int) or 0
        if quantite <= 0:
            del panier[cle]
        else:
            panier[cle]['quantite'] = min(quantite, 999)
        session['panier'] = panier
        session.modified = True
    return redirect(url_for('client.voir_panier'))

@client_bp.route('/retirer_panier/<cle>')
def retirer_panier(cle):
    panier = session.get('panier', {})

    if cle in panier:
        del panier[cle]
        session['panier'] = panier
        session.modified = True
        flash('Article retiré du panier', 'info')

    return redirect(url_for('client.voir_panier'))

@client_bp.route('/vider_panier')
def vider_panier():
    session.pop('panier', None)
    flash('Panier vidé', 'info')

    return redirect(url_for('client.accueil'))

# ==================== VALIDATION COMMANDE & WHATSAPP ====================

@client_bp.route('/valider_commande', methods=['GET', 'POST'])
def valider_commande():
    panier = session.get('panier', {})

    if not panier:
        flash('Votre panier est vide', 'warning')
        return redirect(url_for('client.accueil'))

    boutique = boutique_du_panier(panier)
    if not boutique or not boutique.active:
        session.pop('panier', None)
        flash('Boutique non disponible', 'danger')
        return redirect(url_for('client.accueil'))

    total = sum(item['prix'] * item['quantite'] for item in panier.values())

    if request.method == 'GET':
        return render_template('client/commande.html', panier=panier, total=total, boutique=boutique,
                               zones=[z for z in boutique.zones if z.active],
                               index_quartiers=index_quartiers([z for z in boutique.zones if z.active]),
                               creneaux=creneaux_disponibles())

    client_nom = (request.form.get('client_nom') or '').strip()
    client_telephone = (request.form.get('client_telephone') or '').strip()
    client_adresse = (request.form.get('client_adresse') or '').strip()
    instructions = (request.form.get('instructions') or '').strip()

    if not client_nom or not client_telephone or not client_adresse:
        flash('Nom, téléphone et adresse sont obligatoires', 'danger')
        return render_template('client/commande.html', panier=panier, total=total, boutique=boutique,
                               zones=[z for z in boutique.zones if z.active],
                               index_quartiers=index_quartiers([z for z in boutique.zones if z.active]),
                               creneaux=creneaux_disponibles())


    zones_actives = [z for z in boutique.zones if z.active]
    zone = Zone.query.filter_by(id=request.form.get('zone_id', type=int), boutique_id=boutique.id, active=True).first()
    # Le quartier écrit dans l'adresse fait foi : « Agoè Télessou » est livré en zone Agoè,
    # même si une autre zone (moins chère) a été choisie dans la liste.
    promo, remise, _ = promos.verifier(boutique.id, request.form.get('code_promo'), total,
                                     sum(int(i['quantite']) for i in panier.values()))
    zone_adresse, _ = zone_pour_adresse(client_adresse, zones_actives)
    if zone_adresse:
        zone = zone_adresse
    frais = zone.frais if zone else 0
    # Position GPS gardée seulement si elle est précise (téléphone avec GPS) : une
    # localisation par réseau peut se tromper de plusieurs kilomètres.
    precision = request.form.get('precision', type=float)
    gps_fiable = precision is not None and precision <= 500
    commande = Commande(
        boutique_id=boutique.id,
        client_nom=client_nom,
        client_telephone=client_telephone,
        client_adresse=client_adresse,
        instructions=instructions or None,
        articles_json=list(panier.values()),
        total=total - remise + frais,
        code_promo=promo.code if promo else None,
        remise=remise,
        statut='nouvelle',
        zone=zone,
        frais_livraison=frais,
        creneau=request.form.get('creneau') if request.form.get('creneau') in creneaux_disponibles() else None,
        latitude=lire_coordonnee(request.form.get('latitude'), 90),
        longitude=lire_coordonnee(request.form.get('longitude'), 180),
    )
    if commande.latitude is None or commande.longitude is None or not gps_fiable:
        commande.latitude = commande.longitude = None
    enregistrer_avec_numero(commande, 'numero_commande', Commande.prochain_numero)
    numero_commande = commande.numero
    memoriser_commande(commande)
    if promo:
        promo.utilisations += 1
        db.session.commit()

    # ==================== MESSAGE WHATSAPP POUR LA BOUTIQUE ====================
    message = f"🆕 *NOUVELLE COMMANDE N°{numero_commande}*\n"
    message += "━━━━━━━━━━━━━━━━━━\n"
    message += f"👤 *Client:* {client_nom}\n"
    message += f"📱 *Tél:* {client_telephone}\n"
    message += f"📍 *Adresse:* {client_adresse}\n"
    if commande.zone:
        message += f"🧭 *Zone:* {commande.zone.nom}\n"
    if commande.latitude is not None:
        message += f"🗺️ *Position GPS:* https://maps.google.com/?q={commande.latitude},{commande.longitude}\n"
    if commande.creneau:
        message += f"🕒 *Livraison souhaitée:* {commande.creneau}\n"
    if instructions:
        message += f"\n📝 *Instructions:*\n\"{instructions}\"\n"
    message += "━━━━━━━━━━━━━━━━━━\n"
    message += "📦 *ARTICLES COMMANDÉS:*\n\n"

    for item in panier.values():
        message += f"🔹 *{('n°' + str(item['numero']) + ' · ') if item.get('numero') else ''}{item['nom']}*\n"
        message += f"   Quantité: {item['quantite']}\n"
        message += f"   Prix unitaire: {item['prix']:,.0f} FCFA\n"
        message += f"   Sous-total: {item['prix'] * item['quantite']:,.0f} FCFA\n"
        if item.get('photo'):
            photo_url = item['photo']
            if photo_url.startswith('/'):
                photo_url = request.url_root.rstrip('/') + photo_url
            message += f"   🖼️ *Photo:* {photo_url}\n"
        message += "\n"

    message += "━━━━━━━━━━━━━━━━━━\n"
    if remise:
        message += f"🎁 *Code {promo.code}:* -{remise:,.0f} FCFA\n"
    if frais:
        message += f"🛵 *Livraison ({zone.nom}):* {frais:,.0f} FCFA\n"
    message += f"💰 *TOTAL: {commande.total:,.0f} FCFA*\n"
    message += "━━━━━━━━━━━━━━━━━━"

    numero_boutique = ''.join(c for c in (boutique.whatsapp or '') if c.isdigit())
    whatsapp_boutique_url = f"https://wa.me/{numero_boutique}?text={quote(message)}"

    session.pop('panier', None)

    return render_template('client/confirmation.html',
                           whatsapp_boutique_url=whatsapp_boutique_url,
                           commande=commande,
                           boutique=boutique)

# ==================== PAGE DU LIVREUR (lien secret, sans compte) ====================

@client_bp.route('/livraison/<code>', methods=['GET', 'POST'])
def livraison(code):
    commande = Commande.query.filter_by(code_livraison=code).first()
    if not commande or not commande.livreur:
        return render_template('client/lien_invalide.html'), 404

    if request.method == 'POST' and commande.statut == 'en_livraison':
        stock.changer_statut(commande, 'livree')
        db.session.commit()

    wa_merci = msg.lien_whatsapp(commande.client_telephone, msg.livree_client(commande))         if commande.statut == 'livree' else None
    return render_template('client/livraison.html', commande=commande, wa_merci=wa_merci,
                           fcfa=msg.fcfa)

# ==================== ESPACE DU LIVREUR (lien personnel, installable) ====================

def livreur_par_code(code):
    livreur = Livreur.query.filter_by(code_acces=code).first()
    if not livreur or not livreur.actif or not livreur.boutique.active:
        abort(404)
    return livreur

@client_bp.route('/l/<code>')
def espace_livreur(code):
    livreur = livreur_par_code(code)
    a_livrer = (Commande.query.filter_by(livreur_id=livreur.id, statut='en_livraison')
                .order_by(Commande.date_commande).all())
    debut_jour = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    livrees = (Commande.query.filter(Commande.livreur_id == livreur.id, Commande.statut == 'livree')
               .order_by(Commande.date_livraison.desc()).limit(50).all())
    du_jour = [c for c in livrees if c.date_livraison and c.date_livraison >= debut_jour]
    non_reglees = (Commande.query.filter(Commande.livreur_id == livreur.id, Commande.statut.in_(['livree', 'retournee']),
                                         Commande.reglee.is_(False)).all())
    a_remettre = sum(caisse.a_remettre(c) for c in non_reglees)
    mes_frais = sum(c.frais_livraison or 0 for c in non_reglees)
    return render_template('client/espace_livreur.html', livreur=livreur, a_livrer=a_livrer, livrees=livrees,
                           livrees_jour=len(du_jour), encaisse_jour=sum(c.total for c in du_jour),
                           a_remettre=a_remettre, mes_frais=mes_frais,
                           garde_frais=livreur.boutique.mode_frais != 'boutique_collecte',
                           onglet=request.args.get('onglet', 'a_livrer'), fcfa=msg.fcfa, motifs=Commande.MOTIFS_ECHEC,
                           lien_arrivee=lambda c: msg.lien_whatsapp(c.client_telephone, msg.arrivee_client(c)),
                           suivi_actif=livreur.position_at and (datetime.utcnow() - livreur.position_at).total_seconds() < 120)

@client_bp.route('/l/<code>/livree/<int:commande_id>', methods=['POST'])
def espace_livreur_livree(code, commande_id):
    livreur = livreur_par_code(code)
    commande = Commande.query.filter_by(id=commande_id, livreur_id=livreur.id).first_or_404()
    if commande.statut == 'en_livraison':
        photo = request.files.get('photo')
        if photo and photo.filename:
            commande.photo_preuve = enregistrer_photo(photo, commande.boutique_id)
        stock.changer_statut(commande, 'livree')
        db.session.commit()
        flash(f"Commande n°{commande.numero} livrée à {commande.date_livraison.strftime('%H:%M')}"
              + (" avec photo de preuve" if commande.photo_preuve else "") + ". Merci !", 'success')
    return redirect(url_for('client.espace_livreur', code=code))

@client_bp.route('/l/<code>/arrive/<int:commande_id>', methods=['POST'])
def espace_livreur_arrive(code, commande_id):
    """« Je suis arrivé » : heure enregistrée, téléphone du client qui sonne
    (notification), et le livreur peut aussi envoyer le message WhatsApp."""
    livreur = livreur_par_code(code)
    commande = Commande.query.filter_by(id=commande_id, livreur_id=livreur.id).first_or_404()
    prevenus = 0
    if commande.statut == 'en_livraison':
        commande.date_arrivee = datetime.utcnow()
        db.session.commit()
        prevenus = notifications.envoyer(
            commande, f'🛵 Votre livreur est arrivé !',
            f'{livreur.nom} est devant chez vous avec la commande n°{commande.numero} de '
            f'{commande.boutique.nom_boutique}. À payer : {msg.fcfa(commande.total)}.',
            url_for('client.suivi', code=commande.code_suivi))
    if request.accept_mimetypes.best == 'application/json' or request.is_json:
        return jsonify(ok=commande.statut == 'en_livraison', prevenus=prevenus,
                       heure=commande.date_arrivee.strftime('%H:%M') if commande.date_arrivee else None)
    if commande.date_arrivee:
        flash(f"Arrivée signalée à {commande.date_arrivee.strftime('%H:%M')}"
              + (" : le téléphone du client sonne." if prevenus else ". Envoyez aussi le message WhatsApp au client."), 'success')
    return redirect(url_for('client.espace_livreur', code=code))

@client_bp.route('/l/<code>/position', methods=['POST'])
def espace_livreur_position(code):
    """Position GPS envoyée par le téléphone du livreur pendant ses courses."""
    livreur = livreur_par_code(code)
    actif, message = suivi_gps.enregistrer(livreur, request.get_json(silent=True) or {})
    return jsonify(actif=actif, message=message)

@client_bp.route('/l/<code>/manifest.json')
def manifest_livreur(code):
    """Manifeste propre au livreur : l'application installée s'ouvre sur SON espace."""
    livreur = livreur_par_code(code)
    return jsonify({
        'name': f'LivraPlus Livreur · {livreur.boutique.nom_boutique}',
        'short_name': 'Mes livraisons',
        'id': f'/l/{code}',
        'start_url': f'/l/{code}',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#0b1d35',
        'theme_color': '#0b1d35',
        'lang': 'fr',
        'icons': [
            {'src': '/static/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
            {'src': '/static/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
        ],
    })

# ==================== SUIVI DE COMMANDE (client) ====================

@client_bp.route('/suivi/<code>')
def suivi(code):
    commande = Commande.query.filter_by(code_suivi=code).first()
    if not commande:
        return render_template('client/lien_invalide.html'), 404
    memoriser_commande(commande)
    cle_push = notifications.cles_vapid()[0] if commande.statut in ('nouvelle', 'confirmee', 'en_livraison') else None
    return render_template('client/suivi.html', commande=commande, boutique=commande.boutique, fcfa=msg.fcfa,
                           cle_push=cle_push, position=suivi_gps.situation(commande))

@client_bp.route('/suivi/<code>/etat')
def suivi_etat(code):
    """Interrogé régulièrement par la page de suivi ouverte (pour sonner à l'arrivée)."""
    commande = Commande.query.filter_by(code_suivi=code).first_or_404()
    return jsonify(statut=commande.statut,
                   arrivee=commande.date_arrivee.strftime('%H:%M') if commande.date_arrivee and commande.statut == 'en_livraison' else None,
                   livreur=suivi_gps.situation(commande))

@client_bp.route('/suivi/<code>/ma-position', methods=['POST'])
def suivi_ma_position(code):
    """Le client partage sa position : distance et heure d'arrivée précises."""
    commande = Commande.query.filter_by(code_suivi=code).first_or_404()
    d = request.get_json(silent=True) or {}
    try:
        lat, lng, precision = float(d.get('lat')), float(d.get('lng')), float(d.get('precision') or 0)
    except (TypeError, ValueError):
        return jsonify(ok=False), 400
    if commande.statut not in ('nouvelle', 'confirmee', 'en_livraison') or precision > 500 \
            or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify(ok=False), 400
    commande.latitude, commande.longitude = lat, lng
    db.session.commit()
    return jsonify(ok=True)

@client_bp.route('/suivi/<code>/abonner', methods=['POST'])
def suivi_abonner(code):
    """Le client accepte d'être prévenu : son téléphone sonnera quand le livreur arrive."""
    commande = Commande.query.filter_by(code_suivi=code).first_or_404()
    if commande.statut not in ('nouvelle', 'confirmee', 'en_livraison'):
        return jsonify(ok=False), 400
    return jsonify(ok=notifications.abonner(commande, request.get_json(silent=True)))

@client_bp.route('/suivi/<code>/manifest.json')
def manifest_suivi(code):
    """Ajoutée à l'écran d'accueil (iPhone), la page de suivi peut recevoir l'alerte d'arrivée."""
    commande = Commande.query.filter_by(code_suivi=code).first_or_404()
    return jsonify({
        'name': f'Ma commande · {commande.boutique.nom_boutique}', 'short_name': f'Commande {commande.numero}',
        'id': f'/suivi/{code}', 'start_url': f'/suivi/{code}', 'scope': '/', 'display': 'standalone',
        'background_color': '#ffffff', 'theme_color': '#7c3aed', 'lang': 'fr',
        'icons': [{'src': '/static/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                  {'src': '/static/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}],
    })

# ==================== ÉCHEC DE LIVRAISON (livreur) ====================

@client_bp.route('/l/<code>/echec/<int:commande_id>', methods=['POST'])
def espace_livreur_echec(code, commande_id):
    livreur = livreur_par_code(code)
    commande = Commande.query.filter_by(id=commande_id, livreur_id=livreur.id).first_or_404()
    if commande.statut == 'en_livraison':
        motif = request.form.get('motif') if request.form.get('motif') in Commande.MOTIFS_ECHEC else 'Autre'
        note = (request.form.get('note') or '').strip()
        commande.motif_echec = (motif + (f' : {note}' if note else ''))[:200]
        commande.date_echec = datetime.utcnow()
        stock.changer_statut(commande, 'echec')
        db.session.commit()
        flash(f"Commande n°{commande.numero} signalée « {motif} ». La boutique est prévenue.", 'warning')
    return redirect(url_for('client.espace_livreur', code=code))

# ==================== CODE PROMO (vérification depuis le panier) ====================

@client_bp.route('/api/promo')
def api_promo():
    panier = session.get('panier', {})
    boutique = boutique_du_panier(panier)
    if not boutique:
        return jsonify(ok=False, message='Panier vide')
    total = sum(item['prix'] * item['quantite'] for item in panier.values())
    promo, remise, erreur = promos.verifier(boutique.id, request.args.get('code'), total,
                                          sum(int(i['quantite']) for i in panier.values()))
    if not promo:
        return jsonify(ok=False, message=erreur or 'Code invalide')
    return jsonify(ok=True, code=promo.code, remise=remise, libelle=promo.libelle,
                   message=f'Code {promo.code} appliqué : {msg.fcfa(remise)} de réduction')

# ==================== MES COMMANDES (depuis le catalogue) ====================

COOKIE_COMMANDES = 'lp_mes_commandes'


def codes_memorises():
    """Codes de suivi des commandes passées sur ce téléphone (session + cookie durable)."""
    codes = list(session.get('mes_commandes', []))
    for c in (request.cookies.get(COOKIE_COMMANDES) or '').split('.'):
        if c and c not in codes and len(c) <= 32 and c.replace('-', '').replace('_', '').isalnum():
            codes.append(c)
    return codes[:30]


def memoriser_commande(commande):
    """Ce téléphone retient ses commandes (un an) : le client les retrouve depuis le catalogue."""
    if not commande.code_suivi:
        return
    codes = [commande.code_suivi] + [c for c in codes_memorises() if c != commande.code_suivi]
    session['mes_commandes'] = codes[:30]
    session.modified = True

    @after_this_request
    def _cookie(reponse):
        reponse.set_cookie(COOKIE_COMMANDES, '.'.join(codes[:30]), max_age=365 * 24 * 3600,
                           httponly=True, samesite='Lax', secure=request.is_secure)
        return reponse


def commandes_du_telephone(boutique):
    codes = codes_memorises()
    if not codes:
        return []
    return (Commande.query.filter(Commande.code_suivi.in_(codes), Commande.boutique_id == boutique.id)
            .order_by(Commande.date_commande.desc()).all())


@client_bp.route('/c/<code>/mes-commandes', methods=['GET', 'POST'])
def mes_commandes(code):
    boutique = Boutique.query.filter_by(lien_public=code).first()
    if not boutique or not boutique.active:
        return render_template('client/lien_invalide.html'), 404
    session['last_boutique_id'] = boutique.id

    if request.method == 'POST':
        # Retrouver une commande passée sur un autre téléphone : n° de commande ET téléphone
        numero = request.form.get('numero', type=int)
        tel = ''.join(ch for ch in (request.form.get('telephone') or '') if ch.isdigit())[-8:]
        trouvee = Commande.query.filter_by(boutique_id=boutique.id, numero_commande=numero).first() if numero else None
        if trouvee and len(tel) == 8 and ''.join(ch for ch in trouvee.client_telephone if ch.isdigit()).endswith(tel):
            memoriser_commande(trouvee)
            return redirect(url_for('client.suivi', code=trouvee.code_suivi))
        flash("Aucune commande ne correspond à ce numéro et ce téléphone.", 'warning')
        return redirect(url_for('client.mes_commandes', code=code))

    commandes = commandes_du_telephone(boutique)
    return render_template('client/mes_commandes.html', boutique=boutique, commandes=commandes, fcfa=msg.fcfa)

