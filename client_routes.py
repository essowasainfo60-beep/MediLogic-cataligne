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
import discussions
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

@client_bp.route('/c/<code>/article/<int:numero>')
def voir_article(code, numero):
    """Toutes les photos d'un article, celle choisie par le client mise en avant (?photo=2)."""
    boutique = Boutique.query.filter_by(lien_public=code).first()
    if not boutique or not boutique.active:
        return render_template('client/lien_invalide.html'), 404
    article = Article.query.filter_by(boutique_id=boutique.id, numero=numero).first_or_404()
    photos = [p for p in (article.photos_urls or []) if p]
    choisie = request.args.get('photo', type=int)
    choisie = choisie if choisie and 1 <= choisie <= len(photos) else None
    return render_template('client/article.html', boutique=boutique, article=article, photos=photos, choisie=choisie)

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
    # Photo affichée quand le client a ajouté l'article (ex. le modèle rouge parmi 4 photos)
    photos = [p for p in (article.photos_urls or []) if p]
    index_photo = request.form.get('photo_index', 0, type=int) or 0
    index_photo = index_photo if 0 <= index_photo < len(photos) else 0
    cle = str(article.id) + (('-' + hashlib.md5(choix.encode()).hexdigest()[:8]) if choix else '') \
        + (f'-p{index_photo}' if index_photo else '')
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
            'photo': photos[index_photo] if photos else None,
            'photo_num': index_photo + 1 if len(photos) > 1 else None,   # n° de la photo choisie (sur plusieurs)
            'photos_total': len(photos),
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

def _message_commande(commande):
    b = commande.boutique
    return msg.nouvelle_commande_boutique(
        commande, racine=request.url_root.rstrip('/'),
        lien_article=lambda item: url_for('client.voir_article', code=b.lien_public, numero=item['numero'],
                                          photo=item['photo_num'], _external=True))


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
                               zones=[z for z in boutique.zones if z.active and not z.est_retrait],
                               index_quartiers=index_quartiers([z for z in boutique.zones if z.active and not z.est_retrait]),
                               creneaux=creneaux_disponibles())

    client_nom = (request.form.get('client_nom') or '').strip()
    client_telephone = (request.form.get('client_telephone') or '').strip()
    client_adresse = (request.form.get('client_adresse') or '').strip()
    instructions = (request.form.get('instructions') or '').strip()
    # Le client vient lui-même chercher sa commande à la boutique
    retrait = boutique.zone_retrait if request.form.get('mode_reception') == 'retrait' else None
    if retrait:
        client_adresse = 'Retrait en boutique' + (f' ({boutique.adresse})' if boutique.adresse else '')

    if not client_nom or not client_telephone or not client_adresse:
        flash('Nom, téléphone et adresse sont obligatoires', 'danger')
        return render_template('client/commande.html', panier=panier, total=total, boutique=boutique,
                               zones=[z for z in boutique.zones if z.active and not z.est_retrait],
                               index_quartiers=index_quartiers([z for z in boutique.zones if z.active and not z.est_retrait]),
                               creneaux=creneaux_disponibles())


    zones_actives = [z for z in boutique.zones if z.active and not z.est_retrait]
    zone = retrait or Zone.query.filter_by(id=request.form.get('zone_id', type=int), boutique_id=boutique.id, active=True).first()
    # Le quartier écrit dans l'adresse fait foi : « Agoè Télessou » est livré en zone Agoè,
    # même si une autre zone (moins chère) a été choisie dans la liste.
    promo, remise, _ = promos.verifier(boutique.id, request.form.get('code_promo'), total,
                                     sum(int(i['quantite']) for i in panier.values()))
    zone_adresse, _ = zone_pour_adresse(client_adresse, zones_actives) if not retrait else (None, None)
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
    notifications.envoyer_boutique(
        boutique.id, f'🛒 Nouvelle commande n°{commande.numero}',
        f'{commande.client_nom} · {msg.fcfa(commande.total)}' + (f' · {commande.zone.nom}' if commande.zone else ''),
        url_for('boutique.commande_details', commande_id=commande.id), tag=f'nouvelle-{commande.id}')
    memoriser_commande(commande)
    if promo:
        promo.utilisations += 1
        db.session.commit()

    # ==================== MESSAGE POUR LA BOUTIQUE (WhatsApp ou messagerie LivraPlus) ====================
    message = _message_commande(commande)

    numero_boutique = msg.numero_wa(boutique.whatsapp)
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
                           suivi_actif=livreur.position_at and (datetime.utcnow() - livreur.position_at).total_seconds() < 120,
                           non_lus={c.id: discussions.non_lus(c.discussion, f'livreur:{livreur.id}') for c in a_livrer if c.discussion},
                           non_lus_total=sum(discussions.non_lus(d, f'livreur:{livreur.id}') for d in discussions.discussions_livreur(livreur)),
                           cle_push=notifications.cles_vapid()[0])

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

@client_bp.route('/m/<cle>')
def media_message(cle):
    """Photo ou message vocal d'une discussion (lien secret)."""
    from models import MediaMessage
    m = MediaMessage.query.filter_by(cle=cle).first_or_404()
    reponse = Response(m.donnees, mimetype=m.mime)
    reponse.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
    return reponse


def _api_discussion(d, qui, nom):
    if request.method == 'POST':
        message, erreur = discussions.poster(d, qui, nom, request.form, request.files)
        if erreur:
            return jsonify(ok=False, erreur=erreur), 400
        return jsonify(ok=True, message=discussions.en_dict(message, qui, discussions.lectures(d)))
    liste = discussions.messages(d, qui, request.args.get('apres', 0, type=int))
    discussions.marquer_lu(d, qui)
    autres = [n for q, n in discussions.lectures(d).items() if q != qui]
    return jsonify(messages=liste, lu_jusqu_a=max(autres) if autres else 0)


def _discussion_du_livreur(livreur, discussion_id):
    from models import Discussion
    d = db.session.get(Discussion, discussion_id)
    if not d or not discussions.peut_lire(d, f'livreur:{livreur.id}', livreur):
        abort(404)
    return d


@client_bp.route('/l/<code>/discussions')
def discussions_livreur(code):
    livreur = livreur_par_code(code)
    qui = f'livreur:{livreur.id}'
    lignes = []
    for d in discussions.discussions_livreur(livreur):
        dernier = discussions.dernier_message(d)
        lignes.append({'d': d, 'dernier': dernier, 'apercu': discussions.apercu(dernier) if dernier else '',
                       'non_lus': discussions.non_lus(d, qui)})
    return render_template('client/discussions_livreur.html', livreur=livreur, lignes=lignes)


@client_bp.route('/l/<code>/discussions/<int:discussion_id>')
def discussion_livreur(code, discussion_id):
    livreur = livreur_par_code(code)
    d = _discussion_du_livreur(livreur, discussion_id)
    c = d.commande
    return render_template('discussion.html',
                           titre=f'Commande n°{c.numero} · {c.client_nom}' if c else (
                               f'🔒 {livreur.boutique.nom_boutique} (privé)' if d.est_privee else f'👥 {livreur.boutique.nom_boutique} · tous les livreurs'),
                           sous_titre=(c.client_adresse if c else 'Seuls vous et la boutique voyez cette discussion' if d.est_privee
                                       else 'La boutique et tous les livreurs voient ces messages'),
                           secours_wa=msg.lien_whatsapp(c.client_telephone, f'Bonjour {c.client_nom}, je suis votre livreur ({livreur.boutique.nom_boutique}).') if c else None,
                           retour=url_for('client.discussions_livreur', code=code), retour_libelle='Mes discussions',
                           url_messages=url_for('client.api_discussion_livreur', code=code, discussion_id=d.id),
                           url_envoyer=url_for('client.api_discussion_livreur', code=code, discussion_id=d.id),
                           rapides=discussions.MESSAGES_RAPIDES['livreur'] if c else ['Bonjour 👋', 'Je suis disponible pour une course',
                                                                                       'Je passe faire mon versement'])


@client_bp.route('/l/<code>/api/discussions/<int:discussion_id>/messages', methods=['GET', 'POST'])
def api_discussion_livreur(code, discussion_id):
    livreur = livreur_par_code(code)
    d = _discussion_du_livreur(livreur, discussion_id)
    return _api_discussion(d, f'livreur:{livreur.id}', livreur.nom)


@client_bp.route('/l/<code>/commande/<int:commande_id>/discussion')
def discussion_commande_livreur(code, commande_id):
    livreur = livreur_par_code(code)
    commande = Commande.query.filter_by(id=commande_id, livreur_id=livreur.id).first_or_404()
    return redirect(url_for('client.discussion_livreur', code=code, discussion_id=discussions.discussion_commande(commande).id))


@client_bp.route('/l/<code>/api/non-lus')
def non_lus_livreur(code):
    livreur = livreur_par_code(code)
    qui = f'livreur:{livreur.id}'
    return jsonify(non_lus=sum(discussions.non_lus(d, qui) for d in discussions.discussions_livreur(livreur)),
                   courses=Commande.query.filter_by(livreur_id=livreur.id, statut='en_livraison').count())

@client_bp.route('/l/<code>/alertes/abonner', methods=['POST'])
def alertes_livreur(code):
    livreur = livreur_par_code(code)
    ok = notifications.abonner_livreur(livreur, request.get_json(silent=True))
    return jsonify(ok=ok), (200 if ok else 400)


@client_bp.route('/suivi/<code>/discussion')
def discussion_client(code):
    commande = Commande.query.filter_by(code_suivi=code).first()
    if not commande:
        return render_template('client/lien_invalide.html'), 404
    memoriser_commande(commande)
    d = discussions.discussion_commande(commande)
    b = commande.boutique
    return render_template('discussion.html', boutique=b,
                           titre=f'Commande n°{commande.numero}',
                           sous_titre=f'{b.nom_boutique}' + (f' et votre livreur {commande.livreur.nom}' if commande.livreur else ''),
                           secours_wa=msg.lien_whatsapp(b.whatsapp, f'Bonjour, je vous ai écrit au sujet de ma commande n°{commande.numero}.') if b.whatsapp else None,
                           retour=url_for('client.suivi', code=code), retour_libelle='Suivi de ma commande',
                           url_messages=url_for('client.api_discussion_client', code=code),
                           url_envoyer=url_for('client.api_discussion_client', code=code),
                           rapides=discussions.MESSAGES_RAPIDES['client'],
                           aide='Posez vos questions à la boutique et au livreur : texte, photo ou message vocal.')


@client_bp.route('/suivi/<code>/envoyer-commande', methods=['POST'])
def envoyer_commande_messagerie(code):
    """Le client envoie sa commande à la boutique par la messagerie LivraPlus."""
    commande = Commande.query.filter_by(code_suivi=code).first_or_404()
    d = discussions.discussion_commande(commande)
    deja = discussions.Message.query.filter(discussions.Message.discussion_id == d.id, discussions.Message.auteur == 'client',
                                            discussions.Message.texte.like('🆕%')).first()
    if not deja:
        discussions.poster(d, 'client', commande.client_nom, {'type': 'texte', 'texte': _message_commande(commande).replace('*', '')}, {})
    memoriser_commande(commande)
    return redirect(url_for('client.discussion_client', code=code))

@client_bp.route('/suivi/<code>/api/messages', methods=['GET', 'POST'])
def api_discussion_client(code):
    commande = Commande.query.filter_by(code_suivi=code).first_or_404()
    return _api_discussion(discussions.discussion_commande(commande), 'client', commande.client_nom)


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
                           messages_non_lus=discussions.non_lus(commande.discussion, 'client') if commande.discussion else 0,
                           cle_push=cle_push, position=suivi_gps.situation(commande))

@client_bp.route('/suivi/<code>/etat')
def suivi_etat(code):
    """Interrogé régulièrement par la page de suivi ouverte (pour sonner à l'arrivée)."""
    commande = Commande.query.filter_by(code_suivi=code).first_or_404()
    return jsonify(statut=commande.statut,
                   arrivee=commande.date_arrivee.strftime('%H:%M') if commande.date_arrivee and commande.statut == 'en_livraison' else None,
                   livreur=suivi_gps.situation(commande),
                   messages_non_lus=discussions.non_lus(commande.discussion, 'client') if commande.discussion else 0)

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
        notifications.envoyer_boutique(
            commande.boutique_id, f'⚠️ Échec de livraison n°{commande.numero}',
            f'{livreur.nom} : {commande.motif_echec} ({commande.client_nom})',
            url_for('boutique.commande_details', commande_id=commande.id), tag=f'echec-{commande.id}')
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

