from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, Boutique, Vendeur, Article, Commande
from utils import upload_to_imgbb, upload_multiple_images
from datetime import datetime

boutique_bp = Blueprint('boutique', __name__)

# ==================== INSCRIPTION & CONNEXION ====================

@boutique_bp.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if request.method == 'POST':
        nom_boutique = request.form.get('nom_boutique')
        whatsapp = request.form.get('whatsapp')
        proprietaire_nom = request.form.get('proprietaire_nom')
        proprietaire_prenom = request.form.get('proprietaire_prenom')
        email = request.form.get('email')
        mot_de_passe = request.form.get('mot_de_passe')
        confirmer_mdp = request.form.get('confirmer_mdp')
        question_secrete = request.form.get('question_secrete')
        reponse_secrete = request.form.get('reponse_secrete')
        
        # Vérifications
        if mot_de_passe != confirmer_mdp:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return redirect(url_for('boutique.inscription'))
        
        # Vérifier force mot de passe (min 8 caractères, 1 maj, 1 min, 1 chiffre, 1 symbole)
        import re
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$', mot_de_passe):
            flash('Le mot de passe doit contenir au moins 8 caractères, une majuscule, une minuscule, un chiffre et un symbole', 'danger')
            return redirect(url_for('boutique.inscription'))
        
        # Vérifier email unique
        if Boutique.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé', 'danger')
            return redirect(url_for('boutique.inscription'))
        
        # Créer la boutique
        nouvelle_boutique = Boutique(
            nom_boutique=nom_boutique,
            proprietaire_nom=proprietaire_nom,
            proprietaire_prenom=proprietaire_prenom,
            email=email,
            question_secrete=question_secrete,
            whatsapp=whatsapp,  # ← AJOUTE CETTE LIGNE
            active=False  # En attente d'activation par l'admin
        )
        nouvelle_boutique.set_mot_de_passe(mot_de_passe)
        nouvelle_boutique.set_reponse_secrete(reponse_secrete)
        
        db.session.add(nouvelle_boutique)
        db.session.commit()
        
        flash('Inscription réussie ! En attente d\'activation par l\'administrateur.', 'success')
        return redirect(url_for('boutique.connexion'))
    
    return render_template('boutique/inscription.html')

@boutique_bp.route('/connexion', methods=['GET', 'POST'])
def connexion():
    if request.method == 'POST':
        email = request.form.get('email')
        mot_de_passe = request.form.get('mot_de_passe')
        
        boutique = Boutique.query.filter_by(email=email).first()
        
        if boutique and boutique.verifier_mot_de_passe(mot_de_passe):
            if not boutique.active:
                flash('Votre compte n\'est pas encore activé par l\'administrateur', 'warning')
                return redirect(url_for('boutique.connexion'))
            
            login_user(boutique)
            flash(f'Bonjour {boutique.proprietaire_prenom} !', 'success')
            return redirect(url_for('boutique.dashboard'))
        else:
            flash('Email ou mot de passe incorrect', 'danger')
    
    return render_template('boutique/connexion.html')

@boutique_bp.route('/mot_passe_oublie', methods=['GET', 'POST'])
def mot_passe_oublie():
    if request.method == 'POST':
        email = request.form.get('email')
        reponse_secrete = request.form.get('reponse_secrete')
        nouveau_mdp = request.form.get('nouveau_mdp')
        
        boutique = Boutique.query.filter_by(email=email).first()
        
        if boutique and boutique.verifier_reponse_secrete(reponse_secrete):
            import re
            if re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$', nouveau_mdp):
                boutique.set_mot_de_passe(nouveau_mdp)
                db.session.commit()
                flash('Mot de passe réinitialisé avec succès !', 'success')
                return redirect(url_for('boutique.connexion'))
            else:
                flash('Le mot de passe doit contenir au moins 8 caractères, une majuscule, une minuscule, un chiffre et un symbole', 'danger')
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
    
    return render_template('boutique/dashboard.html', 
                         articles_count=articles_count,
                         vendeurs_count=vendeurs_count,
                         commandes_count=commandes_count)

# ==================== GESTION DU LOGO ====================

@boutique_bp.route('/logo', methods=['GET', 'POST'])
@login_required
def gerer_logo():
    if request.method == 'POST':
        logo = request.files.get('logo')
        if logo and logo.filename:
            url = upload_to_imgbb(logo, f"logo_boutique_{current_user.id}")
            if url:
                current_user.logo_url = url
                db.session.commit()
                flash('Logo mis à jour avec succès !', 'success')
            else:
                flash('Erreur lors de l\'upload du logo', 'danger')
    
    return render_template('boutique/logo.html')

# ==================== GESTION DES ARTICLES ====================

@boutique_bp.route('/articles')
@login_required
def articles():
    articles_list = Article.query.filter_by(boutique_id=current_user.id, archive=False).order_by(Article.created_at.desc()).all()
    return render_template('boutique/articles.html', articles=articles_list)

@boutique_bp.route('/ajouter_article', methods=['GET', 'POST'])
@login_required
def ajouter_article():
    if request.method == 'POST':
        nom = request.form.get('nom')
        description = request.form.get('description')
        prix = float(request.form.get('prix'))
        photos = request.files.getlist('photos')
        
        # Upload des photos vers ImgBB
        urls = upload_multiple_images(photos, current_user.id)
        
        nouvel_article = Article(
            boutique_id=current_user.id,
            nom=nom,
            description=description,
            prix=prix,
            photos_urls=urls
        )
        
        db.session.add(nouvel_article)
        db.session.commit()
        
        flash('Article ajouté avec succès !', 'success')
        return redirect(url_for('boutique.articles'))
    
    return render_template('boutique/ajouter_article.html')

@boutique_bp.route('/modifier_article/<int:article_id>', methods=['GET', 'POST'])
@login_required
def modifier_article(article_id):
    article = Article.query.get_or_404(article_id)
    
    if article.boutique_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.articles'))
    
    if request.method == 'POST':
        article.nom = request.form.get('nom')
        article.description = request.form.get('description')
        article.prix = float(request.form.get('prix'))
        
        nouvelles_photos = request.files.getlist('nouvelles_photos')
        if nouvelles_photos and nouvelles_photos[0].filename:
            nouvelles_urls = upload_multiple_images(nouvelles_photos, current_user.id, article.id)
            article.photos_urls.extend(nouvelles_urls)
        
        db.session.commit()
        flash('Article modifié avec succès !', 'success')
        return redirect(url_for('boutique.articles'))
    
    return render_template('boutique/modifier_article.html', article=article)

@boutique_bp.route('/supprimer_photo/<int:article_id>/<int:photo_index>')
@login_required
def supprimer_photo(article_id, photo_index):
    article = Article.query.get_or_404(article_id)
    
    if article.boutique_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.articles'))
    
    if 0 <= photo_index < len(article.photos_urls):
        article.photos_urls.pop(photo_index)
        db.session.commit()
        flash('Photo supprimée', 'success')
    
    return redirect(url_for('boutique.modifier_article', article_id=article_id))

@boutique_bp.route('/archiver_article/<int:article_id>')
@login_required
def archiver_article(article_id):
    article = Article.query.get_or_404(article_id)
    
    if article.boutique_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.articles'))
    
    article.archive = True
    db.session.commit()
    flash('Article archivé', 'warning')
    return redirect(url_for('boutique.articles'))

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
        email = request.form.get('email')
        mot_de_passe = request.form.get('mot_de_passe')
        
        if Vendeur.query.filter_by(email=email).first():
            flash('Cet email est déjà utilisé', 'danger')
            return redirect(url_for('boutique.ajouter_vendeur'))
        
        nouveau_vendeur = Vendeur(
            boutique_id=current_user.id,
            nom=nom,
            prenom=prenom,
            email=email
        )
        nouveau_vendeur.set_mot_de_passe(mot_de_passe)
        
        db.session.add(nouveau_vendeur)
        db.session.commit()
        
        flash(f'Vendeur {prenom} {nom} ajouté avec succès !', 'success')
        return redirect(url_for('boutique.vendeurs'))
    
    return render_template('boutique/ajouter_vendeur.html')

@boutique_bp.route('/desactiver_vendeur/<int:vendeur_id>')
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
    commandes_list = Commande.query.filter_by(boutique_id=current_user.id).order_by(Commande.date_commande.desc()).all()
    return render_template('boutique/commandes.html', commandes=commandes_list)

@boutique_bp.route('/commande_details/<int:commande_id>')
@login_required
def commande_details(commande_id):
    commande = Commande.query.get_or_404(commande_id)
    
    if commande.boutique_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.commandes'))
    
    commande.lu = True
    db.session.commit()
    
    return render_template('boutique/commande_details.html', commande=commande)

@boutique_bp.route('/envoyer_confirmation_client/<int:commande_id>')
@login_required
def envoyer_confirmation_client(commande_id):
    commande = Commande.query.get_or_404(commande_id)
    
    if commande.boutique_id != current_user.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('boutique.commandes'))
    
    # Récupérer les articles depuis le JSON
    articles = commande.articles_json
    
    # Construire le message de confirmation pour le client
    message = f"✅ *COMMANDE CONFIRMÉE*\n"
    message += f"━━━━━━━━━━━━━━━━━━\n"
    message += f"Bonjour {commande.client_nom},\n\n"
    message += f"Nous avons bien reçu votre commande n°{commande.id}.\n\n"
    message += f"📦 *Récapitulatif:*\n"
    
    for article in articles:
        message += f"   • {article['nom']} x{article['quantite']} = {article['prix'] * article['quantite']:,.0f} FCFA\n"
    
    message += f"\n💰 *TOTAL: {commande.total:,.0f} FCFA*\n\n"
    message += f"📞 Votre commande est en cours de traitement.\n"
    message += f"Merci pour votre confiance !"
    
    # Encoder le message
    from urllib.parse import quote
    message_encode = quote(message)
    
    # Lien WhatsApp
    numero_client = commande.client_telephone.replace(' ', '').replace('+', '')
    whatsapp_url = f"https://wa.me/{numero_client}?text={message_encode}"
    
    return redirect(whatsapp_url)

@boutique_bp.route('/modifier_whatsapp', methods=['POST'])
@login_required
def modifier_whatsapp():
    whatsapp = request.form.get('whatsapp')
    if whatsapp:
        current_user.whatsapp = whatsapp
        db.session.commit()
        flash('Numéro WhatsApp mis à jour !', 'success')
    else:
        flash('Numéro invalide', 'danger')
    return redirect(url_for('boutique.dashboard'))