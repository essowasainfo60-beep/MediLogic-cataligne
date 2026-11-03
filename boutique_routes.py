import csv
import io
import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, Response, render_template, redirect, url_for, flash, request, session, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user

import messages_whatsapp as msg
import stock
import webauthn_service
from models import (db, Boutique, Vendeur, Article, Commande, CleBiometrique, Livreur, Zone,
                    MouvementStock, Retour, nouveau_code_lien, enregistrer_avec_numero)
from utils import enregistrer_photo, enregistrer_photos, supprimer_photo_stockee, TAILLE_LOGO_PX
from zones_modele import ZONES_LOME

boutique_bp = Blueprint('boutique', __name__)

MDP_FORT = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$')
MSG_MDP_FAIBLE = 'Le mot de passe doit contenir au moins 8 caractères, une majuscule, une minuscule, un chiffre et un symbole'


def lire_prix(valeur):
    try:
        prix = float((valeur or '').replace(' ', '').replace(',', '.'))
        return prix if prix >= 0 else None
    except ValueError:
        return None


def article_de_la_boutique(article_id):
    article = Article.query.get_or_404(article_id)
    return article if article.boutique_id == current_user.id else None


def zones_actives():
    return Zone.query.filter_by(boutique_id=current_user.id, active=True).order_by(Zone.nom).all()


def commande_de_la_boutique(commande_id):
    commande = Commande.query.get_or_404(commande_id)
    return commande if commande.boutique_id == current_user.id else None

# ==================== INSCRIPTION & CONNEXION ====================

@boutique_bp.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe') or ''

        if mot_de_passe != request.form.get('confirmer_mdp'):
            flash('Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('boutique.inscription'))

        if not MDP_FORT.match(mot_de_passe):
            flash(MSG_MDP_FAIBLE, 'danger')
            return redirect(url_for('boutique.inscription'))

        if Boutique.query.filter(db.func.lower(Boutique.email) == email).first():
            flash('Cet email est déjà utilisé', 'danger')
            return redirect(url_for('boutique.inscription'))

        nouvelle_boutique = Boutique(
            nom_boutique=request.form.get('nom_boutique'),
            proprietaire_nom=request.form.get('proprietaire_nom'),
            proprietaire_prenom=request.form.get('proprietaire_prenom'),
            email=email,
            question_secrete=request.form.get('question_secrete'),
            whatsapp=request.form.get('whatsapp'),
            active=False  # En attente d'activation par l'admin
        )
        nouvelle_boutique.set_mot_de_passe(mot_de_passe)
        nouvelle_boutique.set_reponse_secrete(request.form.get('reponse_secrete') or '')

        db.session.add(nouvelle_boutique)
        db.session.commit()

        flash('Inscription réussie ! En attente d\'activation par l\'administrateur.', 'success')
        return redirect(url_for('boutique.connexion'))

    return render_template('boutique/inscription.html')

@boutique_bp.route('/connexion', methods=['GET', 'POST'])
def connexion():
    if current_user.is_authenticated and isinstance(current_user, Boutique):
        return redirect(url_for('boutique.dashboard'))
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        boutique = Boutique.query.filter(db.func.lower(Boutique.email) == email).first()

        if boutique and boutique.verifier_mot_de_passe(request.form.get('mot_de_passe') or ''):
            if not boutique.active:
                flash('Votre compte n\'est pas encore activé par l\'administrateur', 'warning')
                return redirect(url_for('boutique.connexion'))

            login_user(boutique)
            flash(f'Bonjour {boutique.proprietaire_prenom} !', 'success')
            return redirect(url_for('boutique.dashboard'))
        flash('Email ou mot de passe incorrect', 'danger')

    return render_template('boutique/connexion.html')

# ==================== FACE ID / EMPREINTE (WebAuthn) ====================

@boutique_bp.route('/connexion/biometrie/options', methods=['POST'])
def biometrie_connexion_options():
    options_json, challenge = webauthn_service.options_connexion(request)
    session['webauthn_connexion'] = challenge
    return jsonify(success=True, options=json.loads(options_json))

@boutique_bp.route('/connexion/biometrie/verifier', methods=['POST'])
def biometrie_connexion_verifier():
    challenge = session.pop('webauthn_connexion', None)
    if not challenge:
        return jsonify(success=False, error='Session expirée, réessayez.'), 400
    try:
        boutique = webauthn_service.verifier_connexion(request, (request.get_json(silent=True) or {}).get('credential'), challenge)
    except Exception as e:
        return jsonify(success=False, error=str(e) if isinstance(e, ValueError) else 'Vérification refusée.'), 400
    if not boutique.active:
        return jsonify(success=False, error="Votre compte n'est pas encore activé par l'administrateur."), 403
    login_user(boutique, remember=True)
    return jsonify(success=True, redirect=url_for('boutique.dashboard'))

@boutique_bp.route('/biometrie/inscription/options', methods=['POST'])
@login_required
def biometrie_inscription_options():
    options_json, challenge = webauthn_service.options_inscription(request, current_user)
    session['webauthn_inscription'] = challenge
    return jsonify(success=True, options=json.loads(options_json))

@boutique_bp.route('/biometrie/inscription/verifier', methods=['POST'])
@login_required
def biometrie_inscription_verifier():
    challenge = session.pop('webauthn_inscription', None)
    if not challenge:
        return jsonify(success=False, error='Session expirée, réessayez.'), 400
    data = request.get_json(silent=True) or {}
    try:
        webauthn_service.verifier_inscription(request, current_user, data.get('credential'), challenge, data.get('libelle'))
    except Exception as e:
        return jsonify(success=False, error=f"Échec de l'enregistrement : {e}"), 400
    return jsonify(success=True)

@boutique_bp.route('/biometrie/retirer/<int:cle_id>', methods=['POST'])
@login_required
def biometrie_retirer(cle_id):
    cle = CleBiometrique.query.filter_by(id=cle_id, boutique_id=current_user.id).first_or_404()
    db.session.delete(cle)
    db.session.commit()
    flash('Appareil retiré : il ne peut plus se connecter par Face ID / empreinte', 'warning')
    return redirect(url_for('boutique.dashboard'))

# ==================== LIEN CLIENTS ====================

@boutique_bp.route('/regenerer_lien', methods=['POST'])
@login_required
def regenerer_lien():
    current_user.lien_public = nouveau_code_lien()
    db.session.commit()
    flash('Nouveau lien créé : l\'ancien lien ne fonctionne plus. Partagez le nouveau à vos clients.', 'success')
    return redirect(url_for('boutique.dashboard'))

@boutique_bp.route('/mot_passe_oublie', methods=['GET', 'POST'])
def mot_passe_oublie():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        nouveau_mdp = request.form.get('nouveau_mdp') or ''
        boutique = Boutique.query.filter(db.func.lower(Boutique.email) == email).first()

        if boutique and boutique.verifier_reponse_secrete(request.form.get('reponse_secrete') or ''):
            if MDP_FORT.match(nouveau_mdp):
                boutique.set_mot_de_passe(nouveau_mdp)
                db.session.commit()
                flash('Mot de passe réinitialisé avec succès !', 'success')
                return redirect(url_for('boutique.connexion'))
            flash(MSG_MDP_FAIBLE, 'danger')
        else:
            flash('Email ou réponse incorrecte', 'danger')

    return render_template('boutique/mot_passe_oublie.html')

@boutique_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie', 'success')
    return redirect(url_for('boutique.connexion'))

# ==================== TABLEAU DE BORD BOUTIQUE ====================

@boutique_bp.route('/dashboard')
@login_required
def dashboard():
    articles_count = Article.query.filter_by(boutique_id=current_user.id, archive=False).count()
    vendeurs_count = Vendeur.query.filter_by(boutique_id=current_user.id, actif=True).count()
    commandes_count = Commande.query.filter_by(boutique_id=current_user.id).count()
    nouvelles_count = Commande.query.filter_by(boutique_id=current_user.id, statut='nouvelle').count()
    en_livraison_count = Commande.query.filter_by(boutique_id=current_user.id, statut='en_livraison').count()

    return render_template('boutique/dashboard.html',
                           en_livraison_count=en_livraison_count,
                           articles_count=articles_count,
                           vendeurs_count=vendeurs_count,
                           commandes_count=commandes_count,
                           nouvelles_count=nouvelles_count)

# ==================== GESTION DU LOGO ====================

@boutique_bp.route('/logo')
@login_required
def gerer_logo():
    return redirect(url_for('boutique.profil'))

@boutique_bp.route('/profil', methods=['GET', 'POST'])
@login_required
def profil():
    """Identité de la boutique : nom, logo, description, adresse, WhatsApp."""
    if request.method == 'POST':
        nom = (request.form.get('nom_boutique') or '').strip()
        if not nom:
            flash('Le nom de la boutique est obligatoire', 'danger')
            return redirect(url_for('boutique.profil'))
        current_user.nom_boutique = nom[:100]
        current_user.description = (request.form.get('description') or '').strip() or None
        current_user.adresse = (request.form.get('adresse') or '').strip()[:255] or None
        whatsapp = (request.form.get('whatsapp') or '').strip()
        if whatsapp:
            current_user.whatsapp = whatsapp

        logo = request.files.get('logo')
        if logo and logo.filename:
            url = enregistrer_photo(logo, current_user.id, taille_max=TAILLE_LOGO_PX)
            if url:
                ancien = current_user.logo_url
                current_user.logo_url = url
                supprimer_photo_stockee(ancien, current_user.id)
            else:
                flash('Le logo n\'est pas une image valide : il n\'a pas été changé', 'warning')
        if request.form.get('retirer_logo') and not (logo and logo.filename):
            supprimer_photo_stockee(current_user.logo_url, current_user.id)
            current_user.logo_url = None
        db.session.commit()
        flash('Votre boutique est à jour !', 'success')
        return redirect(url_for('boutique.profil'))

    return render_template('boutique/profil.html')

# ==================== GESTION DES ARTICLES ====================

@boutique_bp.route('/articles')
@login_required
def articles():
    articles_list = Article.query.filter_by(boutique_id=current_user.id, archive=False).order_by(Article.created_at.desc()).all()
    return render_template('boutique/articles.html', articles=articles_list, archives=False)

@boutique_bp.route('/articles_archives')
@login_required
def articles_archives():
    articles_list = Article.query.filter_by(boutique_id=current_user.id, archive=True).order_by(Article.created_at.desc()).all()
    return render_template('boutique/articles.html', articles=articles_list, archives=True)

@boutique_bp.route('/ajouter_article', methods=['GET', 'POST'])
@login_required
def ajouter_article():
    if request.method == 'POST':
        nom = (request.form.get('nom') or '').strip()
        prix = lire_prix(request.form.get('prix'))
        if not nom or prix is None:
            flash('Le nom et un prix valide sont obligatoires', 'danger')
            return redirect(url_for('boutique.ajouter_article'))

        urls, echecs = enregistrer_photos(request.files.getlist('photos'), current_user.id)

        article = Article(
            boutique_id=current_user.id,
            nom=nom,
            description=(request.form.get('description') or '').strip(),
            prix=prix,
            photos_urls=urls,
        )
        enregistrer_avec_numero(article, 'numero', Article.prochain_numero)
        stock_initial = request.form.get('stock', type=int)
        if stock_initial is not None and stock_initial >= 0:
            article.stock = 0
            stock.mouvement(article, stock_initial, 'entree', note='Stock initial')
            db.session.commit()

        flash(f'Article n°{article.numero} ajouté avec succès !', 'success')
        if echecs:
            flash(f'{echecs} fichier(s) ignoré(s) : ce ne sont pas des images valides', 'warning')
        return redirect(url_for('boutique.articles'))

    return render_template('boutique/ajouter_article.html')

@boutique_bp.route('/modifier_article/<int:article_id>', methods=['GET', 'POST'])
@login_required
def modifier_article(article_id):
    article = article_de_la_boutique(article_id)
    if not article:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.articles'))

    if request.method == 'POST':
        nom = (request.form.get('nom') or '').strip()
        prix = lire_prix(request.form.get('prix'))
        if not nom or prix is None:
            flash('Le nom et un prix valide sont obligatoires', 'danger')
            return redirect(url_for('boutique.modifier_article', article_id=article.id))

        article.nom = nom
        article.description = (request.form.get('description') or '').strip()
        article.prix = prix

        urls, echecs = enregistrer_photos(request.files.getlist('nouvelles_photos'), current_user.id)
        if urls:
            # Nouvelle liste (et non .extend) pour que SQLAlchemy détecte le changement du JSON
            article.photos_urls = list(article.photos_urls or []) + urls

        db.session.commit()
        flash('Article modifié avec succès !', 'success')
        if echecs:
            flash(f'{echecs} fichier(s) ignoré(s) : ce ne sont pas des images valides', 'warning')
        return redirect(url_for('boutique.articles'))

    return render_template('boutique/modifier_article.html', article=article)

@boutique_bp.route('/supprimer_photo/<int:article_id>/<int:photo_index>', methods=['POST'])
@login_required
def supprimer_photo(article_id, photo_index):
    article = article_de_la_boutique(article_id)
    if not article:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.articles'))

    photos = list(article.photos_urls or [])
    if 0 <= photo_index < len(photos):
        supprimer_photo_stockee(photos.pop(photo_index), current_user.id)
        article.photos_urls = [url for url in photos if url and url.strip()]
        db.session.commit()
        flash('Photo supprimée', 'success')
    else:
        flash('Photo introuvable', 'danger')

    return redirect(url_for('boutique.modifier_article', article_id=article_id))

@boutique_bp.route('/photo_principale/<int:article_id>/<int:photo_index>', methods=['POST'])
@login_required
def photo_principale(article_id, photo_index):
    """Place une photo en première position (celle affichée dans le catalogue)."""
    article = article_de_la_boutique(article_id)
    if not article:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.articles'))

    photos = list(article.photos_urls or [])
    if 0 < photo_index < len(photos):
        photos.insert(0, photos.pop(photo_index))
        article.photos_urls = photos
        db.session.commit()
        flash('Photo principale changée', 'success')
    return redirect(url_for('boutique.modifier_article', article_id=article_id))

@boutique_bp.route('/archiver_article/<int:article_id>', methods=['POST'])
@login_required
def archiver_article(article_id):
    article = article_de_la_boutique(article_id)
    if not article:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.articles'))

    article.archive = True
    db.session.commit()
    flash('Article archivé : il n\'est plus visible par les clients', 'warning')
    return redirect(url_for('boutique.articles'))

@boutique_bp.route('/restaurer_article/<int:article_id>', methods=['POST'])
@login_required
def restaurer_article(article_id):
    article = article_de_la_boutique(article_id)
    if article:
        article.archive = False
        db.session.commit()
        flash('Article remis en vente', 'success')
    return redirect(url_for('boutique.articles_archives'))

# ==================== GESTION DES VENDEURS ====================

@boutique_bp.route('/vendeurs')
@login_required
def vendeurs():
    vendeurs_list = Vendeur.query.filter_by(boutique_id=current_user.id).all()
    return render_template('boutique/vendeurs.html', vendeurs=vendeurs_list)

@boutique_bp.route('/ajouter_vendeur', methods=['GET', 'POST'])
@login_required
def ajouter_vendeur():
    if request.method == 'POST':
        nom = request.form.get('nom')
        prenom = request.form.get('prenom')
        email = (request.form.get('email') or '').strip().lower()

        if Vendeur.query.filter(db.func.lower(Vendeur.email) == email).first():
            flash('Cet email est déjà utilisé', 'danger')
            return redirect(url_for('boutique.ajouter_vendeur'))

        nouveau_vendeur = Vendeur(boutique_id=current_user.id, nom=nom, prenom=prenom, email=email)
        nouveau_vendeur.set_mot_de_passe(request.form.get('mot_de_passe') or '')

        db.session.add(nouveau_vendeur)
        db.session.commit()

        flash(f'Vendeur {prenom} {nom} ajouté avec succès !', 'success')
        return redirect(url_for('boutique.vendeurs'))

    return render_template('boutique/ajouter_vendeur.html')

@boutique_bp.route('/desactiver_vendeur/<int:vendeur_id>', methods=['POST'])
@login_required
def desactiver_vendeur(vendeur_id):
    vendeur = Vendeur.query.get_or_404(vendeur_id)

    if vendeur.boutique_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.vendeurs'))

    vendeur.actif = False
    db.session.commit()
    flash(f'Vendeur {vendeur.prenom} {vendeur.nom} désactivé', 'warning')
    return redirect(url_for('boutique.vendeurs'))

# ==================== GESTION DES COMMANDES ====================

@boutique_bp.route('/commandes')
@login_required
def commandes():
    statut = request.args.get('statut')
    if statut not in Commande.STATUTS:
        statut = None

    requete = Commande.query.filter_by(boutique_id=current_user.id)
    if statut:
        requete = requete.filter_by(statut=statut)
    commandes_list = requete.order_by(Commande.date_commande.desc()).all()

    compteurs = dict(db.session.query(Commande.statut, db.func.count(Commande.id))
                     .filter(Commande.boutique_id == current_user.id)
                     .group_by(Commande.statut).all())
    return render_template('boutique/commandes.html', commandes=commandes_list,
                           statut_actif=statut, compteurs=compteurs, statuts=Commande.STATUTS)

@boutique_bp.route('/commande_details/<int:commande_id>')
@login_required
def commande_details(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if not commande:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.commandes'))

    if not commande.lu:
        commande.lu = True
        db.session.commit()

    wa_client = wa_livreur = None
    if commande.livreur:
        wa_client = msg.lien_whatsapp(commande.client_telephone, msg.livreur_en_route_client(commande))
        lien_livraison = url_for('client.livraison', code=commande.code_livraison, _external=True)
        wa_livreur = msg.lien_whatsapp(commande.livreur.telephone, msg.course_livreur(commande, lien_livraison))

    livreurs = Livreur.query.filter_by(boutique_id=current_user.id, actif=True).order_by(Livreur.nom).all()
    # Livreur proposé : celui déjà choisi, sinon le livreur attitré de la zone
    livreur_propose = commande.livreur_id or (commande.zone.livreur_id if commande.zone else None)
    return render_template('boutique/commande_details.html', commande=commande, statuts=Commande.STATUTS,
                           livreurs=livreurs, zones=zones_actives(), livreur_propose=livreur_propose,
                           wa_client=wa_client, wa_livreur=wa_livreur,
                           gboutik_url=current_app.config['GBOUTIK_URL'])

@boutique_bp.route('/commande/<int:commande_id>/frais', methods=['POST'])
@login_required
def changer_frais_commande(commande_id):
    commande = commande_de_la_boutique(commande_id)
    frais = lire_prix(request.form.get('frais_livraison'))
    if commande and frais is not None and commande.statut not in ('livree', 'retournee'):
        commande.frais_livraison = frais
        commande.recalculer_total()
        db.session.commit()
        flash(f'Frais de livraison : {msg.fcfa(frais)} · total {msg.fcfa(commande.total)}', 'success')
    return redirect(url_for('boutique.commande_details', commande_id=commande_id) + '#livraison')

@boutique_bp.route('/commande/<int:commande_id>/zone', methods=['POST'])
@login_required
def changer_zone_commande(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if commande:
        commande.zone = Zone.query.filter_by(id=request.form.get('zone_id', type=int),
                                             boutique_id=current_user.id).first()
        if commande.statut not in ('livree', 'retournee'):  # le tarif de la zone s'applique
            commande.frais_livraison = commande.zone.frais if commande.zone else 0
            commande.recalculer_total()
        db.session.commit()
    return redirect(url_for('boutique.commande_details', commande_id=commande_id) + '#livraison')

@boutique_bp.route('/nouvelle_commande', methods=['GET', 'POST'])
@login_required
def nouvelle_commande():
    """Commande saisie par la boutique : client d'un live TikTok, d'un appel, de Facebook…"""
    catalogue = (Article.query.filter_by(boutique_id=current_user.id, archive=False)
                 .order_by(Article.numero).all())

    if request.method == 'POST':
        f = request.form
        lignes = []
        par_id = {a.id: a for a in catalogue}
        for article_id, qte in zip(f.getlist('article_id'), f.getlist('quantite')):
            article = par_id.get(int(article_id)) if article_id.isdigit() else None
            quantite = int(qte) if qte.isdigit() else 0
            if article and quantite > 0:
                lignes.append({'nom': article.nom, 'prix': article.prix, 'quantite': quantite, 'article_id': article.id,
                               'numero': article.numero,
                               'boutique_id': current_user.id, 'photo': (article.photos_urls or [None])[0]})
        # Articles hors catalogue (montrés en live mais pas encore en ligne)
        for nom, prix, qte in zip(f.getlist('libre_nom'), f.getlist('libre_prix'), f.getlist('libre_quantite')):
            prix = lire_prix(prix)
            quantite = int(qte) if qte.isdigit() else 0
            if nom.strip() and prix is not None and quantite > 0:
                lignes.append({'nom': nom.strip(), 'prix': prix, 'quantite': quantite,
                               'boutique_id': current_user.id, 'photo': None})

        client_nom = (f.get('client_nom') or '').strip()
        client_telephone = (f.get('client_telephone') or '').strip()
        client_adresse = (f.get('client_adresse') or '').strip()
        if not lignes or not client_nom or not client_telephone or not client_adresse:
            flash('Client (nom, téléphone, adresse) et au moins un article sont obligatoires', 'danger')
            return render_template('boutique/nouvelle_commande.html', catalogue=catalogue,
                                   sources=Commande.SOURCES, zones=zones_actives(), form=f)

        zone = Zone.query.filter_by(id=f.get('zone_id', type=int), boutique_id=current_user.id).first()
        frais = lire_prix(f.get('frais_livraison'))
        if frais is None:
            frais = zone.frais if zone else 0
        commande = Commande(
            boutique_id=current_user.id,
            client_nom=client_nom,
            client_telephone=client_telephone,
            client_adresse=client_adresse,
            instructions=(f.get('instructions') or '').strip() or None,
            articles_json=lignes,
            total=sum(l['prix'] * l['quantite'] for l in lignes) + frais,
            frais_livraison=frais,
            statut='confirmee',  # la boutique l'a prise elle-même : déjà confirmée
            source=f.get('source') if f.get('source') in Commande.SOURCES else 'autre',
            zone=zone,
            lu=True,
        )
        enregistrer_avec_numero(commande, 'numero_commande', Commande.prochain_numero)
        flash(f'Commande n°{commande.numero} enregistrée. Attribuez-la à un livreur et imprimez la facture.', 'success')
        return redirect(url_for('boutique.commande_details', commande_id=commande.id) + '#livraison')

    return render_template('boutique/nouvelle_commande.html', catalogue=catalogue,
                           sources=Commande.SOURCES, zones=zones_actives(), form=request.args)

@boutique_bp.route('/commande/<int:commande_id>/attribuer', methods=['POST'])
@login_required
def attribuer_livreur(commande_id):
    commande = commande_de_la_boutique(commande_id)
    livreur = Livreur.query.filter_by(id=request.form.get('livreur_id', type=int),
                                      boutique_id=current_user.id, actif=True).first()
    if not commande or not livreur:
        flash('Choisissez un livreur', 'danger')
        return redirect(url_for('boutique.commande_details', commande_id=commande_id))

    commande.livreur = livreur
    stock.changer_statut(commande, 'en_livraison')
    commande.lu = True
    if not commande.code_livraison:
        commande.code_livraison = nouveau_code_lien()
    db.session.commit()
    flash(f'Commande confiée à {livreur.nom}. Prévenez maintenant le client et le livreur avec les boutons WhatsApp.', 'success')
    return redirect(url_for('boutique.commande_details', commande_id=commande.id) + '#livraison')

@boutique_bp.route('/commande/<int:commande_id>/imprimer')
@login_required
def imprimer_commande(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if not commande:
        return redirect(url_for('boutique.commandes'))
    format_papier = '80' if request.args.get('format') == '80' else 'a4'
    return render_template('boutique/imprimer_commande.html', commande=commande, boutique=current_user,
                           format_papier=format_papier, fcfa=msg.fcfa)

# ==================== LIVREURS ====================

@boutique_bp.route('/livreurs', methods=['GET', 'POST'])
@login_required
def livreurs():
    if request.method == 'POST':
        nom = (request.form.get('nom') or '').strip()
        telephone = (request.form.get('telephone') or '').strip()
        if not nom or sum(c.isdigit() for c in telephone) < 8:
            flash('Nom et numéro WhatsApp valides obligatoires', 'danger')
        else:
            db.session.add(Livreur(boutique_id=current_user.id, nom=nom, telephone=telephone))
            db.session.commit()
            flash(f'Livreur {nom} ajouté', 'success')
        return redirect(url_for('boutique.livreurs'))

    liste = Livreur.query.filter_by(boutique_id=current_user.id).order_by(Livreur.actif.desc(), Livreur.nom).all()
    en_cours = dict(db.session.query(Commande.livreur_id, db.func.count(Commande.id))
                    .filter(Commande.boutique_id == current_user.id, Commande.statut == 'en_livraison')
                    .group_by(Commande.livreur_id).all())
    zones = Zone.query.filter_by(boutique_id=current_user.id).order_by(Zone.active.desc(), Zone.nom).all()
    return render_template('boutique/livreurs.html', livreurs=liste, en_cours=en_cours, zones=zones,
                           livreurs_actifs=[l for l in liste if l.actif])

@boutique_bp.route('/livreurs/<int:livreur_id>/basculer', methods=['POST'])
@login_required
def basculer_livreur(livreur_id):
    livreur = Livreur.query.filter_by(id=livreur_id, boutique_id=current_user.id).first_or_404()
    livreur.actif = not livreur.actif
    db.session.commit()
    flash(f"{livreur.nom} {'réactivé' if livreur.actif else 'désactivé'}", 'success')
    return redirect(url_for('boutique.livreurs'))

@boutique_bp.route('/commande/<int:commande_id>/statut', methods=['POST'])
@login_required
def changer_statut_commande(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if not commande:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.commandes'))

    statut = request.form.get('statut')
    if statut in Commande.STATUTS and statut != 'retournee':  # « retournée » passe par un retour
        stock.changer_statut(commande, statut)
        commande.lu = True
        db.session.commit()
        flash(f'Commande n°{commande.numero} : {commande.statut_libelle}', 'success')
    return redirect(request.referrer or url_for('boutique.commandes'))

@boutique_bp.route('/envoyer_confirmation_client/<int:commande_id>')
@login_required
def envoyer_confirmation_client(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if not commande:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.commandes'))

    # Envoyer la confirmation fait passer une commande nouvelle à "confirmée"
    if commande.statut == 'nouvelle':
        stock.changer_statut(commande, 'confirmee')
        db.session.commit()

    return redirect(msg.lien_whatsapp(commande.client_telephone, msg.confirmation_client(commande)))

@boutique_bp.route('/modifier_whatsapp', methods=['POST'])
@login_required
def modifier_whatsapp():
    whatsapp = (request.form.get('whatsapp') or '').strip()
    if whatsapp:
        current_user.whatsapp = whatsapp
        db.session.commit()
        flash('Numéro WhatsApp mis à jour !', 'success')
    else:
        flash('Numéro invalide', 'danger')
    return redirect(url_for('boutique.dashboard'))

# ==================== ZONES DE LIVRAISON ====================

@boutique_bp.route('/zones', methods=['POST'])
@login_required
def ajouter_zone():
    nom = (request.form.get('nom') or '').strip()
    if not nom:
        flash('Donnez un nom à la zone', 'danger')
    else:
        livreur = Livreur.query.filter_by(id=request.form.get('livreur_id', type=int), boutique_id=current_user.id).first()
        db.session.add(Zone(boutique_id=current_user.id, nom=nom, frais=lire_prix(request.form.get('frais')) or 0,
                            quartiers=(request.form.get('quartiers') or '').strip() or None, livreur=livreur))
        db.session.commit()
        flash(f'Zone « {nom} » créée', 'success')
    return redirect(url_for('boutique.livreurs') + '#zones')

@boutique_bp.route('/zones/<int:zone_id>', methods=['POST'])
@login_required
def modifier_zone(zone_id):
    zone = Zone.query.filter_by(id=zone_id, boutique_id=current_user.id).first_or_404()
    if 'active' in request.form:
        zone.active = request.form.get('active') == '1'
    else:
        zone.nom = (request.form.get('nom') or zone.nom).strip()
        zone.quartiers = (request.form.get('quartiers') or '').strip() or None
        zone.frais = lire_prix(request.form.get('frais')) or 0
        zone.livreur = Livreur.query.filter_by(id=request.form.get('livreur_id', type=int),
                                               boutique_id=current_user.id).first()
    db.session.commit()
    flash(f'Zone « {zone.nom} » mise à jour', 'success')
    return redirect(url_for('boutique.livreurs') + '#zones')

# ==================== HISTORIQUE ====================

def _lire_date(valeur):
    try:
        return datetime.strptime(valeur or '', '%Y-%m-%d')
    except ValueError:
        return None


def _filtrer_historique(args):
    requete = Commande.query.filter_by(boutique_id=current_user.id)
    du, au = _lire_date(args.get('du')), _lire_date(args.get('au'))
    if du:
        requete = requete.filter(Commande.date_commande >= du)
    if au:
        requete = requete.filter(Commande.date_commande < au + timedelta(days=1))
    if args.get('statut') in Commande.STATUTS:
        requete = requete.filter_by(statut=args['statut'])
    if args.get('source') in Commande.SOURCES:
        requete = requete.filter_by(source=args['source'])
    if args.get('livreur', type=int):
        requete = requete.filter_by(livreur_id=args.get('livreur', type=int))
    if args.get('zone', type=int):
        requete = requete.filter_by(zone_id=args.get('zone', type=int))
    q = (args.get('q') or '').strip()
    if q:
        motif = f'%{q}%'
        requete = requete.filter(db.or_(Commande.client_nom.ilike(motif), Commande.client_telephone.ilike(motif),
                                        Commande.client_adresse.ilike(motif)))
    return requete.order_by(Commande.date_commande.desc())

@boutique_bp.route('/historique')
@login_required
def historique():
    commandes_list = _filtrer_historique(request.args).all()
    livrees = [c for c in commandes_list if c.statut == 'livree']
    resume = {
        'nombre': len(commandes_list),
        'livrees': len(livrees),
        'en_livraison': sum(c.statut == 'en_livraison' for c in commandes_list),
        'annulees': sum(c.statut == 'annulee' for c in commandes_list),
        'montant_livre': sum(c.total for c in livrees),
        'frais_livraison': sum(c.frais_livraison or 0 for c in livrees),
    }
    # Bilan par livreur : commandes livrées et montant encaissé
    par_livreur = {}
    for c in livrees:
        nom = c.livreur.nom if c.livreur else 'Sans livreur'
        n, m = par_livreur.get(nom, (0, 0))
        par_livreur[nom] = (n + 1, m + c.total)
    return render_template('boutique/historique.html', commandes=commandes_list, resume=resume,
                           par_livreur=sorted(par_livreur.items(), key=lambda x: -x[1][1]),
                           livreurs=Livreur.query.filter_by(boutique_id=current_user.id).order_by(Livreur.nom).all(),
                           zones=Zone.query.filter_by(boutique_id=current_user.id).order_by(Zone.nom).all(),
                           statuts=Commande.STATUTS, sources=Commande.SOURCES, f=request.args, fcfa=msg.fcfa)

@boutique_bp.route('/historique.csv')
@login_required
def historique_csv():
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=';')
    w.writerow(['N°', 'Date commande', 'Provenance', 'Client', 'Téléphone', 'Adresse', 'Zone', 'Articles',
                'Sous-total (FCFA)', 'Frais livraison (FCFA)', 'Total (FCFA)', 'Statut', 'Livreur', 'Date livraison'])
    for c in _filtrer_historique(request.args):
        w.writerow([c.numero, c.date_commande.strftime('%d/%m/%Y %H:%M'), c.source_libelle, c.client_nom,
                    c.client_telephone, c.client_adresse, c.zone.nom if c.zone else '',
                    ', '.join(f"{a['nom']} x{a['quantite']}" for a in c.articles_json),
                    f'{c.sous_total:.0f}', f'{c.frais_livraison or 0:.0f}', f'{c.total:.0f}', c.statut_libelle, c.livreur.nom if c.livreur else '',
                    c.date_livraison.strftime('%d/%m/%Y %H:%M') if c.date_livraison else ''])
    # BOM UTF-8 : Excel affiche alors correctement les accents
    return Response('\ufeff' + sortie.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=historique-commandes.csv'})

# ==================== RETOURS / ÉCHANGES ====================

@boutique_bp.route('/commande/<int:commande_id>/retour', methods=['GET', 'POST'])
@login_required
def retour_commande(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if not commande or commande.statut not in ('livree', 'retournee'):
        flash('Seule une commande livrée peut faire l\'objet d\'un retour', 'danger')
        return redirect(url_for('boutique.commande_details', commande_id=commande_id))

    restant = stock.quantites_retournables(commande)
    if request.method == 'POST':
        type_retour = 'echange' if request.form.get('type') == 'echange' else 'retour'
        lignes = []
        for i, ligne in enumerate(commande.articles_json):
            qte = min(max(request.form.get(f'qte_{i}', 0, type=int) or 0, 0), restant.get(i, 0))
            if qte:
                lignes.append({'index': i, 'nom': ligne['nom'], 'prix': ligne['prix'], 'quantite': qte,
                               'article_id': ligne.get('article_id')})
        if not lignes:
            flash('Indiquez au moins un article rapporté', 'danger')
            return redirect(url_for('boutique.retour_commande', commande_id=commande.id))

        motif = (request.form.get('motif') or '').strip() or None
        retour = Retour(commande=commande, type=type_retour, motif=motif, lignes=lignes,
                        montant=sum(l['prix'] * l['quantite'] for l in lignes))
        db.session.add(retour)
        for l in lignes:  # les articles rapportés reviennent en stock
            stock.mouvement(stock.article_de_ligne(l, commande.boutique_id), l['quantite'], 'retour', commande,
                            f"{retour.type_libelle} - commande n°{commande.numero}" + (f" : {motif}" if motif else ''))
        if type_retour == 'retour' and not any(stock.quantites_retournables(commande).values()):
            commande.statut = 'retournee'
        db.session.commit()

        if type_retour == 'echange':
            flash('Retour enregistré et remis en stock. Saisissez maintenant les articles donnés en échange.', 'success')
            return redirect(url_for('boutique.nouvelle_commande', source=commande.source if commande.source != 'catalogue' else 'autre',
                                    client_nom=commande.client_nom, client_telephone=commande.client_telephone,
                                    client_adresse=commande.client_adresse, zone_id=commande.zone_id or '',
                                    instructions=f'Échange de la commande n°{commande.numero}'))
        flash(f'Retour enregistré : {msg.fcfa(retour.montant)} à rembourser au client. Articles remis en stock.', 'success')
        return redirect(url_for('boutique.commande_details', commande_id=commande.id))

    return render_template('boutique/retour.html', commande=commande, restant=restant, fcfa=msg.fcfa)

# ==================== INVENTAIRE / STOCK ====================

@boutique_bp.route('/inventaire', methods=['GET', 'POST'])
@login_required
def inventaire():
    articles_list = (Article.query.filter_by(boutique_id=current_user.id)
                     .order_by(Article.archive, Article.numero).all())
    if request.method == 'POST':
        changements = 0
        for article in articles_list:
            valeur = (request.form.get(f'compte_{article.id}') or '').strip()
            if valeur == '' or not valeur.isdigit():
                continue
            compte = int(valeur)
            if article.stock is None:  # début du suivi pour cet article
                article.stock = 0
                stock.mouvement(article, compte, 'inventaire', note='Début du suivi (inventaire)')
                changements += 1
            elif compte != article.stock:
                stock.mouvement(article, compte - article.stock, 'inventaire',
                                note=f'Inventaire : compté {compte}, attendu {article.stock}')
                changements += 1
        db.session.commit()
        flash(f'Inventaire enregistré : {changements} article(s) corrigé(s).' if changements
              else 'Inventaire enregistré : aucun écart.', 'success')
        return redirect(url_for('boutique.inventaire'))

    suivis = [a for a in articles_list if a.stock is not None]
    resume = {
        'suivis': len(suivis),
        'unites': sum(max(a.stock, 0) for a in suivis),
        'valeur': sum(max(a.stock, 0) * a.prix for a in suivis),
        'ruptures': sum(a.stock <= 0 for a in suivis),
        'faibles': sum(0 < a.stock <= 3 for a in suivis),
    }
    return render_template('boutique/inventaire.html', articles=articles_list, resume=resume, fcfa=msg.fcfa)

@boutique_bp.route('/inventaire/entree', methods=['POST'])
@login_required
def entree_stock():
    article = Article.query.filter_by(id=request.form.get('article_id', type=int), boutique_id=current_user.id).first_or_404()
    quantite = request.form.get('quantite', type=int) or 0
    if quantite <= 0:
        flash('Quantité invalide', 'danger')
    else:
        if article.stock is None:
            article.stock = 0
        stock.mouvement(article, quantite, 'entree', note=(request.form.get('note') or 'Réception de marchandise'))
        db.session.commit()
        flash(f'+{quantite} « {article.nom} » : stock {article.stock}', 'success')
    return redirect(url_for('boutique.inventaire'))

@boutique_bp.route('/inventaire/mouvements')
@login_required
def mouvements_stock():
    requete = MouvementStock.query.filter_by(boutique_id=current_user.id)
    article_id = request.args.get('article', type=int)
    if article_id:
        requete = requete.filter_by(article_id=article_id)
    return render_template('boutique/mouvements.html',
                           mouvements=requete.order_by(MouvementStock.date.desc()).limit(500).all(),
                           articles=Article.query.filter_by(boutique_id=current_user.id).order_by(Article.nom).all(),
                           article_id=article_id)


@boutique_bp.route('/zones/modele', methods=['GET', 'POST'])
@login_required
def zones_modele():
    """Démarrage rapide : zones types de Lomé, à ajuster avant création."""
    existantes = {z.nom.strip().lower() for z in current_user.zones}
    if request.method == 'POST':
        creees = 0
        for i in request.form.getlist('choisie'):
            nom = (request.form.get(f'nom_{i}') or '').strip()
            if not nom or nom.lower() in existantes:
                continue
            livreur = Livreur.query.filter_by(id=request.form.get(f'livreur_{i}', type=int),
                                              boutique_id=current_user.id).first()
            db.session.add(Zone(boutique_id=current_user.id, nom=nom[:100],
                                quartiers=(request.form.get(f'quartiers_{i}') or '').strip() or None,
                                frais=lire_prix(request.form.get(f'frais_{i}')) or 0, livreur=livreur))
            existantes.add(nom.lower())
            creees += 1
        db.session.commit()
        flash(f'{creees} zone(s) créée(s). Vos clients verront le prix de livraison en choisissant leur zone.', 'success')
        return redirect(url_for('boutique.livreurs') + '#zones')

    livreurs_actifs = Livreur.query.filter_by(boutique_id=current_user.id, actif=True).order_by(Livreur.nom).all()
    return render_template('boutique/zones_modele.html', modele=ZONES_LOME, existantes=existantes,
                           livreurs=livreurs_actifs)
