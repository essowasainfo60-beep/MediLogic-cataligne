"""Approvisionnement (comme dans Ma Boutik) : un bon de réception = un fournisseur, plusieurs
articles (ou variantes), leur quantité et leur prix d'achat.

  - le stock augmente (bonne variante), chaque ligne est tracée dans l'historique du stock ;
  - le prix d'achat de l'article prend le prix de ce dernier achat (pour le bénéfice) ;
  - payé tout de suite : une charge « Achat de marchandises » sort de la caisse ;
    sinon le bon reste « à payer au fournisseur » jusqu'à son paiement."""
from datetime import datetime

import caisse
import stock
from models import db, Article, Approvisionnement


def fournisseurs(boutique_id):
    """Fournisseurs déjà utilisés (pour les proposer à la saisie)."""
    return sorted({f for (f,) in db.session.query(Approvisionnement.fournisseur)
                   .filter(Approvisionnement.boutique_id == boutique_id, Approvisionnement.fournisseur.isnot(None)).distinct()})


def a_payer(boutique_id):
    return (Approvisionnement.query.filter_by(boutique_id=boutique_id, paye=False)
            .order_by(Approvisionnement.date).all())


def enregistrer(boutique, fournisseur, lignes, payer, par, note=None):
    """lignes : [{'article_id', 'cle', 'quantite', 'prix_achat'}]. Renvoie (bon, None) ou (None, erreur)."""
    fournisseur = (fournisseur or '').strip()[:120] or None
    propres = []
    for l in lignes or []:
        try:
            article_id, quantite = int(l.get('article_id')), int(l.get('quantite') or 0)
        except (TypeError, ValueError):
            return None, 'Ligne invalide'
        article = db.session.get(Article, article_id)
        if not article or article.boutique_id != boutique.id:
            return None, 'Un article n\'existe plus'
        if quantite <= 0 or quantite > 100000:
            return None, f'« {article.nom} » : quantité invalide'
        cle = l.get('cle') or None
        if article.suit_variantes:
            if not cle or cle not in dict(article.combinaisons()):
                return None, f'« {article.nom} » : choisissez la taille / couleur reçue'
        else:
            cle = None
        pa = l.get('prix_achat')
        try:
            pa = round(float(pa), 2) if pa not in (None, '') else None
        except (TypeError, ValueError):
            return None, f'« {article.nom} » : prix d\'achat invalide'
        if pa is not None and pa < 0:
            return None, f'« {article.nom} » : prix d\'achat invalide'
        propres.append((article, cle, quantite, pa))
    if not propres:
        return None, 'Ajoutez au moins un article reçu'
    total = round(sum(q * (pa or 0) for _, _, q, pa in propres), 2)
    bon = Approvisionnement(boutique_id=boutique.id, fournisseur=fournisseur, total=total, paye=bool(payer) or total == 0,
                            par=(par or '')[:120], note=(note or '').strip()[:200] or None, lignes=[])
    db.session.add(bon)
    db.session.flush()
    for article, cle, q, pa in propres:
        if article.stock is None:
            article.stock = 0
        stock.mouvement(article, q, 'entree', note=f'Approvisionnement n°{bon.id}' + (f' ({fournisseur})' if fournisseur else ''),
                        variante=cle)
        if pa is not None:
            article.prix_achat = pa
        bon.lignes = bon.lignes + [{'article_id': article.id, 'numero': article.numero, 'cle': cle,
                                    'nom': article.nom + (f' ({article.libelle_cle(cle)})' if cle else ''),
                                    'quantite': q, 'prix_achat': pa}]
    if bon.paye and total:
        bon.date_paiement = datetime.utcnow()
        caisse.ajouter(boutique.id, 'charge', -total, f'Approvisionnement n°{bon.id}' + (f' : {fournisseur}' if fournisseur else ''),
                       categorie='Achat de marchandises')
    db.session.commit()
    return bon, None


def payer(bon):
    """Le fournisseur est payé (plus tard) : l'argent sort de la caisse."""
    if bon.paye:
        return 'Ce bon est déjà payé'
    bon.paye, bon.date_paiement = True, datetime.utcnow()
    if bon.total:
        caisse.ajouter(bon.boutique_id, 'charge', -bon.total,
                       f'Paiement fournisseur : approvisionnement n°{bon.id}' + (f' ({bon.fournisseur})' if bon.fournisseur else ''),
                       categorie='Achat de marchandises')
    db.session.commit()
    return None
