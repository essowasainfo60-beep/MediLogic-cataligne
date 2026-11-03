from urllib.parse import quote

from flask import (Blueprint, Response, abort, flash, jsonify, redirect,
                   render_template, request, session, url_for)

from models import db, Boutique, Article, Commande, Photo

client_bp = Blueprint('client', __name__)


def nombre_articles(panier):
    return sum(item['quantite'] for item in panier.values())


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

@client_bp.route('/')
def accueil():
    # Retour à la dernière boutique visitée si elle est toujours active
    last_boutique_id = session.get('last_boutique_id')
    if last_boutique_id:
        boutique = db.session.get(Boutique, last_boutique_id)
        if boutique and boutique.active:
            return redirect(url_for('client.afficher_boutique', boutique_id=last_boutique_id))

    premiere_boutique = Boutique.query.filter_by(active=True).order_by(Boutique.id).first()
    if premiere_boutique:
        return redirect(url_for('client.afficher_boutique', boutique_id=premiere_boutique.id))

    return "Aucune boutique disponible pour le moment"

@client_bp.route('/boutique/<int:boutique_id>')
def afficher_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)

    if not boutique.active:
        session.pop('last_boutique_id', None)
        flash('Cette boutique n\'est pas disponible', 'danger')
        return redirect(url_for('client.accueil'))

    session['last_boutique_id'] = boutique_id
    articles = (Article.query.filter_by(boutique_id=boutique_id, archive=False)
                .order_by(Article.created_at.desc()).all())

    return render_template('client/catalogue.html',
                           boutique=boutique,
                           articles=articles,
                           panier=session.get('panier', {}))

# ==================== GESTION DU PANIER ====================

@client_bp.route('/ajouter_panier', methods=['POST'])
def ajouter_panier():
    article = Article.query.get_or_404(request.form.get('article_id', type=int))
    quantite = max(1, min(request.form.get('quantite', 1, type=int) or 1, 999))
    veut_json = request.accept_mimetypes.best == 'application/json'

    if article.archive or not article.boutique.active:
        if veut_json:
            return jsonify(success=False, message='Article indisponible'), 400
        flash('Article indisponible', 'danger')
        return redirect(url_for('client.accueil'))

    panier = session.get('panier', {})
    # Un panier = une seule boutique (une commande part vers un seul WhatsApp)
    if any(item.get('boutique_id') != article.boutique_id for item in panier.values()):
        panier = {}

    cle = str(article.id)
    if cle in panier:
        panier[cle]['quantite'] += quantite
    else:
        panier[cle] = {
            'nom': article.nom,
            'prix': article.prix,
            'quantite': quantite,
            'boutique_id': article.boutique_id,
            'photo': (article.photos_urls or [None])[0],
        }

    session['panier'] = panier
    session.modified = True

    if veut_json:
        return jsonify(success=True, panier_count=nombre_articles(panier))
    flash(f'{article.nom} ajouté au panier', 'success')
    return redirect(url_for('client.afficher_boutique', boutique_id=article.boutique_id))

@client_bp.route('/panier')
def voir_panier():
    panier = session.get('panier', {})
    total = sum(item['prix'] * item['quantite'] for item in panier.values())
    boutique = boutique_du_panier(panier)
    if not boutique and session.get('last_boutique_id'):
        boutique = db.session.get(Boutique, session['last_boutique_id'])

    return render_template('client/panier.html', panier=panier, total=total, boutique=boutique)

@client_bp.route('/modifier_quantite/<int:article_id>', methods=['POST'])
def modifier_quantite(article_id):
    panier = session.get('panier', {})
    cle = str(article_id)
    if cle in panier:
        quantite = request.form.get('quantite', 1, type=int) or 0
        if quantite <= 0:
            del panier[cle]
        else:
            panier[cle]['quantite'] = min(quantite, 999)
        session['panier'] = panier
        session.modified = True
    return redirect(url_for('client.voir_panier'))

@client_bp.route('/retirer_panier/<int:article_id>')
def retirer_panier(article_id):
    panier = session.get('panier', {})

    if str(article_id) in panier:
        del panier[str(article_id)]
        session['panier'] = panier
        session.modified = True
        flash('Article retiré du panier', 'info')

    return redirect(url_for('client.voir_panier'))

@client_bp.route('/vider_panier')
def vider_panier():
    session.pop('panier', None)
    flash('Panier vidé', 'info')

    last_boutique_id = session.get('last_boutique_id')
    if last_boutique_id:
        return redirect(url_for('client.afficher_boutique', boutique_id=last_boutique_id))
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
        return render_template('client/commande.html', panier=panier, total=total, boutique=boutique)

    client_nom = (request.form.get('client_nom') or '').strip()
    client_telephone = (request.form.get('client_telephone') or '').strip()
    client_adresse = (request.form.get('client_adresse') or '').strip()
    instructions = (request.form.get('instructions') or '').strip()

    if not client_nom or not client_telephone or not client_adresse:
        flash('Nom, téléphone et adresse sont obligatoires', 'danger')
        return render_template('client/commande.html', panier=panier, total=total, boutique=boutique)

    # Numéro propre à la boutique : 1, 2, 3… (max + 1, sûr même après suppression)
    dernier = db.session.query(db.func.max(Commande.numero_commande)).filter(
        Commande.boutique_id == boutique.id).scalar() or 0
    numero_commande = dernier + 1

    commande = Commande(
        boutique_id=boutique.id,
        client_nom=client_nom,
        client_telephone=client_telephone,
        client_adresse=client_adresse,
        instructions=instructions or None,
        articles_json=list(panier.values()),
        total=total,
        numero_commande=numero_commande,
        statut='nouvelle',
    )
    db.session.add(commande)
    db.session.commit()

    # ==================== MESSAGE WHATSAPP POUR LA BOUTIQUE ====================
    message = f"🆕 *NOUVELLE COMMANDE N°{numero_commande}*\n"
    message += "━━━━━━━━━━━━━━━━━━\n"
    message += f"👤 *Client:* {client_nom}\n"
    message += f"📱 *Tél:* {client_telephone}\n"
    message += f"📍 *Adresse:* {client_adresse}\n"
    if instructions:
        message += f"\n📝 *Instructions:*\n\"{instructions}\"\n"
    message += "━━━━━━━━━━━━━━━━━━\n"
    message += "📦 *ARTICLES COMMANDÉS:*\n\n"

    for item in panier.values():
        message += f"🔹 *{item['nom']}*\n"
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
    message += f"💰 *TOTAL: {total:,.0f} FCFA*\n"
    message += "━━━━━━━━━━━━━━━━━━"

    numero_boutique = ''.join(c for c in (boutique.whatsapp or '') if c.isdigit())
    whatsapp_boutique_url = f"https://wa.me/{numero_boutique}?text={quote(message)}"

    session.pop('panier', None)

    return render_template('client/confirmation.html',
                           whatsapp_boutique_url=whatsapp_boutique_url,
                           commande=commande,
                           boutique=boutique)
