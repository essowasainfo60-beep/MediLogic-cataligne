import json
from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from models import db, Boutique, Article, Commande
from datetime import datetime
from urllib.parse import quote

client_bp = Blueprint('client', __name__)

# ==================== ACCUEIL & SELECTION BOUTIQUE ====================

@client_bp.route('/')
def accueil():
    return redirect(url_for('boutique.connexion'))

@client_bp.route('/boutique/<int:boutique_id>')
def afficher_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    
    if not boutique.active:
        flash('Cette boutique n\'est pas disponible', 'danger')
        return redirect(url_for('client.accueil'))
    
    articles = Article.query.filter_by(boutique_id=boutique_id, archive=False).all()
    panier = session.get('panier', {})
    
    return render_template('client/catalogue.html', 
                         boutique=boutique, 
                         articles=articles,
                         panier=panier)

# ==================== GESTION DU PANIER ====================

@client_bp.route('/ajouter_panier', methods=['POST'])
def ajouter_panier():
    article_id = int(request.form.get('article_id'))
    quantite = int(request.form.get('quantite', 1))
    boutique_id = int(request.form.get('boutique_id'))
    
    article = Article.query.get_or_404(article_id)
    
    if 'panier' not in session:
        session['panier'] = {}
    
    panier = session['panier']
    
    if str(article_id) in panier:
        panier[str(article_id)]['quantite'] += quantite
    else:
        panier[str(article_id)] = {
            'nom': article.nom,
            'prix': article.prix,
            'quantite': quantite,
            'boutique_id': boutique_id
        }
    
    session['panier'] = panier
    session.modified = True
    
    flash(f'{article.nom} ajouté au panier', 'success')
    return redirect(url_for('client.afficher_boutique', boutique_id=boutique_id))

@client_bp.route('/panier')
def voir_panier():
    panier = session.get('panier', {})
    total = sum(item['prix'] * item['quantite'] for item in panier.values())
    
    boutique_id = None
    for item in panier.values():
        boutique_id = item.get('boutique_id')
        break
    
    boutique = Boutique.query.get(boutique_id) if boutique_id else None
    
    return render_template('client/panier.html', panier=panier, total=total, boutique=boutique)

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
    return redirect(url_for('client.accueil'))

# ==================== VALIDATION COMMANDE & WHATSAPP ====================

@client_bp.route('/valider_commande', methods=['GET', 'POST'])
def valider_commande():
    panier = session.get('panier', {})
    
    if not panier:
        flash('Votre panier est vide', 'warning')
        return redirect(url_for('client.accueil'))
    
    boutique_id = None
    for item in panier.values():
        boutique_id = item.get('boutique_id')
        break
    
    boutique = Boutique.query.get(boutique_id)
    
    if not boutique or not boutique.active:
        flash('Boutique non disponible', 'danger')
        return redirect(url_for('client.accueil'))
    
    if request.method == 'POST':
        client_nom = request.form.get('client_nom')
        client_telephone = request.form.get('client_telephone')
        client_adresse = request.form.get('client_adresse')
        instructions = request.form.get('instructions')
        
        total = sum(item['prix'] * item['quantite'] for item in panier.values())
        
        commande = Commande(
            boutique_id=boutique_id,
            client_nom=client_nom,
            client_telephone=client_telephone,
            client_adresse=client_adresse,
            articles_json=list(panier.values()),
            total=total
        )
        
        db.session.add(commande)
        db.session.commit()
        
        # ==================== CALCULER LE NUMÉRO UNIQUE POUR CETTE BOUTIQUE ====================
        numero_commande = Commande.query.filter_by(boutique_id=boutique_id).count()
        commande.numero_commande = numero_commande
        db.session.commit()
        
        # ==================== MESSAGE POUR LA BOUTIQUE ====================
        message_boutique = f"🆕 *NOUVELLE COMMANDE N°{numero_commande}*\n"
        message_boutique += f"━━━━━━━━━━━━━━━━━━\n"
        message_boutique += f"👤 *Client:* {client_nom}\n"
        message_boutique += f"📱 *Tél:*  {client_telephone}\n"
        message_boutique += f"📍 *Adresse:* {client_adresse}\n"
        
        if instructions and instructions.strip():
            message_boutique += f"\n📝 *Instructions:*\n"
            message_boutique += f"\"{instructions.strip()}\"\n"
        
        message_boutique += f"━━━━━━━━━━━━━━━━━━\n"
        message_boutique += f"📦 *ARTICLES COMMANDÉS:*\n\n"
        
        for item in panier.values():
            article = Article.query.filter_by(nom=item['nom'], boutique_id=boutique_id).first()
            
            message_boutique += f"🔹 *{item['nom']}*\n"
            message_boutique += f"   Quantité: {item['quantite']}\n"
            message_boutique += f"   Prix unitaire: {item['prix']:,.0f} FCFA\n"
            message_boutique += f"   Sous-total: {item['prix'] * item['quantite']:,.0f} FCFA\n"
            
            if article and article.photos_urls and len(article.photos_urls) > 0:
                photo_url = article.photos_urls[0]
                message_boutique += f"   🖼️ *Photo:* {photo_url}\n"
            
            message_boutique += f"\n"
        
        message_boutique += f"━━━━━━━━━━━━━━━━━━\n"
        message_boutique += f"💰 *TOTAL: {total:,.0f} FCFA*\n"
        message_boutique += f"━━━━━━━━━━━━━━━━━━\n"
        message_boutique += f"✅ Merci pour votre commande !\n"
        message_boutique += f"📞 Nous vous contacterons sous peu."
        
        # ==================== MESSAGE POUR LE CLIENT ====================
        message_client = f"✅ *COMMANDE CONFIRMÉE N°{numero_commande}*\n"
        message_client += f"━━━━━━━━━━━━━━━━━━\n"
        message_client += f"Bonjour {client_nom},\n\n"
        message_client += f"Nous avons bien reçu votre commande.\n\n"
        message_client += f"📦 *Récapitulatif:*\n"
        
        for item in panier.values():
            message_client += f"   • {item['nom']} x{item['quantite']} = {item['prix'] * item['quantite']:,.0f} FCFA\n"
        
        message_client += f"\n💰 *TOTAL: {total:,.0f} FCFA*\n\n"
        message_client += f"📞 Un agent vous contactera sous peu.\n"
        message_client += f"Merci pour votre confiance !"
        
        # Encodage pour l'URL
        message_boutique_encode = quote(message_boutique)
        message_client_encode = quote(message_client)
        
        # Lien WhatsApp pour la boutique
        numero_boutique = boutique.whatsapp.replace(' ', '').replace('+', '') if boutique.whatsapp else ''
        whatsapp_boutique_url = f"https://wa.me/{numero_boutique}?text={message_boutique_encode}"
        
        print("=== MESSAGE BOUTIQUE ===\n", message_boutique)        
        session.pop('panier', None)
        
        flash('Commande validée avec succès !', 'success')
        return render_template('client/confirmation.html', 
                             whatsapp_boutique_url=whatsapp_boutique_url,
                             commande=commande,
                             boutique=boutique)
    
    total = sum(item['prix'] * item['quantite'] for item in panier.values())
    
    return render_template('client/commande.html', panier=panier, total=total, boutique=boutique)