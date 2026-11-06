"""Stock des articles : toute variation passe par ici et laisse une trace
(MouvementStock). Le stock baisse quand une commande est LIVRÉE ; il est
remis si cette livraison est annulée, et augmente lors d'un retour client."""
from datetime import datetime

import caisse
from models import db, Article, MouvementStock


def article_de_ligne(ligne, boutique_id):
    """Article du catalogue correspondant à une ligne de commande
    (par identifiant, ou par nom pour les commandes plus anciennes)."""
    if ligne.get('article_id'):
        article = db.session.get(Article, ligne['article_id'])
        return article if article and article.boutique_id == boutique_id else None
    return Article.query.filter_by(boutique_id=boutique_id, nom=ligne.get('nom')).first()


def mouvement(article, quantite, type_mouvement, commande=None, note=None):
    """Applique +quantite / -quantite au stock d'un article suivi."""
    if article is None or article.stock is None or not quantite:
        return
    article.stock += quantite
    db.session.add(MouvementStock(
        boutique_id=article.boutique_id, article=article, commande=commande, type=type_mouvement,
        quantite=quantite, stock_apres=article.stock, note=(note or '')[:255] or None,
    ))


def _sortir_stock(commande):
    for ligne in commande.articles_json:
        mouvement(article_de_ligne(ligne, commande.boutique_id), -int(ligne['quantite']), 'vente',
                  commande, f'Commande n°{commande.numero}')
    commande.stock_deduit = True


def _remettre_stock(commande):
    for ligne in commande.articles_json:
        mouvement(article_de_ligne(ligne, commande.boutique_id), int(ligne['quantite']), 'annulation',
                  commande, f'Commande n°{commande.numero} : livraison annulée')
    commande.stock_deduit = False


def changer_statut(commande, statut):
    """Seul point d'entrée pour changer le statut d'une commande (date de
    livraison + stock gérés ici). Ne valide pas la transaction."""
    if statut == commande.statut:
        return
    etait_livree = commande.statut == 'livree'
    if statut == 'livree':
        commande.date_livraison = commande.date_livraison or datetime.utcnow()
        if not commande.stock_deduit:
            _sortir_stock(commande)
        commande.statut = statut
        caisse.commande_livree(commande)
        return
    if statut == 'en_livraison':
        commande.tentatives = (commande.tentatives or 0) + 1
        commande.date_depart = datetime.utcnow()
        commande.date_arrivee = None
    if statut != 'retournee':
        # Retour en arrière (en livraison, annulée…) : la vente n'a pas eu lieu
        commande.date_livraison = None
        if commande.stock_deduit and not commande.retours:
            _remettre_stock(commande)
        if etait_livree:
            caisse.commande_plus_livree(commande)
            commande.livre_par = None
    commande.statut = statut


def quantites_retournables(commande):
    """{index de ligne: quantité encore retournable} (livré moins déjà retourné)."""
    deja = {}
    for r in commande.retours:
        for l in r.lignes:
            deja[l['index']] = deja.get(l['index'], 0) + l['quantite']
    return {i: int(l['quantite']) - deja.get(i, 0) for i, l in enumerate(commande.articles_json)}
