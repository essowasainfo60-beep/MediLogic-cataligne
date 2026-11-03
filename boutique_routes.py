import re
from urllib.parse import quote

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from models import db, Boutique, Vendeur, Article, Commande
from utils import enregistrer_photo, enregistrer_photos, supprimer_photo_stockee, TAILLE_LOGO_PX

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

    return render_template('boutique/dashboard.html',
                           articles_count=articles_count,
                           vendeurs_count=vendeurs_count,
                           commandes_count=commandes_count,
                           nouvelles_count=nouvelles_count)

# ==================== GESTION DU LOGO ====================

@boutique_bp.route('/logo', methods=['GET', 'POST'])
@login_required
def gerer_logo():
    if request.method == 'POST':
        url = enregistrer_photo(request.files.get('logo'), current_user.id, taille_max=TAILLE_LOGO_PX)
        if url:
            ancien = current_user.logo_url
            current_user.logo_url = url
            supprimer_photo_stockee(ancien, current_user.id)
            db.session.commit()
            flash('Logo mis à jour avec succès !', 'success')
        else:
            flash('Ce fichier n\'est pas une image valide', 'danger')
        return redirect(url_for('boutique.gerer_logo'))

    return render_template('boutique/logo.html')

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

        db.session.add(Article(
            boutique_id=current_user.id,
            nom=nom,
            description=(request.form.get('description') or '').strip(),
            prix=prix,
            photos_urls=urls,
        ))
        db.session.commit()

        flash('Article ajouté avec succès !', 'success')
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

    return render_template('boutique/commande_details.html', commande=commande, statuts=Commande.STATUTS)

@boutique_bp.route('/commande/<int:commande_id>/statut', methods=['POST'])
@login_required
def changer_statut_commande(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if not commande:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.commandes'))

    statut = request.form.get('statut')
    if statut in Commande.STATUTS:
        commande.statut = statut
        commande.lu = True
        db.session.commit()
        flash(f'Commande n°{commande.numero_commande or commande.id} : {commande.statut_libelle}', 'success')
    return redirect(request.referrer or url_for('boutique.commandes'))

@boutique_bp.route('/envoyer_confirmation_client/<int:commande_id>')
@login_required
def envoyer_confirmation_client(commande_id):
    commande = commande_de_la_boutique(commande_id)
    if not commande:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.commandes'))

    numero = commande.numero_commande or commande.id
    message = f"✅ *COMMANDE CONFIRMÉE N°{numero}*\n"
    message += "━━━━━━━━━━━━━━━━━━\n"
    message += f"Bonjour {commande.client_nom},\n\n"
    message += "Nous avons bien reçu votre commande.\n\n"
    message += "📦 *Récapitulatif:*\n"
    for article in commande.articles_json:
        message += f"   • {article['nom']} x{article['quantite']} = {article['prix'] * article['quantite']:,.0f} FCFA\n"
    message += f"\n💰 *TOTAL: {commande.total:,.0f} FCFA*\n\n"
    message += "📞 Votre commande est en cours de traitement.\n"
    message += f"Merci pour votre confiance !\n{current_user.nom_boutique}"

    # Envoyer la confirmation fait passer une commande nouvelle à "confirmée"
    if commande.statut == 'nouvelle':
        commande.statut = 'confirmee'
        db.session.commit()

    numero_client = ''.join(c for c in commande.client_telephone if c.isdigit())
    return redirect(f"https://wa.me/{numero_client}?text={quote(message)}")

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
