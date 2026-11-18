"""Synchronisation du stock avec Ma Boutik pendant la transition.

Tant qu'une boutique vend encore dans Ma Boutik, chaque mouvement de stock fait là-bas
(vente, annulation, correction, approvisionnement, produit ajouté / modifié) est envoyé ici,
et le stock du MÊME article (même nom) est ajusté. Les ventes en ligne de LivraPlus baissent
le stock de LivraPlus : il reste donc le stock réel (Ma Boutik + LivraPlus).

Sécurité : chaque boutique a sa clé (seule son empreinte est gardée ici) ; un mouvement porte
une référence unique, il n'est jamais appliqué deux fois même si Ma Boutik le renvoie."""
import hashlib
import hmac
import secrets
from datetime import datetime

import stock
from models import db, Article, Boutique, SynchroMaBoutik, enregistrer_avec_numero

TYPES = {  # type Ma Boutik → (type de mouvement LivraPlus, libellé)
    'vente': ('vente', 'Vente dans Ma Boutik'),
    'annulation': ('annulation', 'Vente annulée dans Ma Boutik'),
    'correction': ('inventaire', 'Correction de vente dans Ma Boutik'),
    'approvisionnement': ('entree', 'Approvisionnement dans Ma Boutik'),
    'inventaire': ('inventaire', 'Stock modifié dans Ma Boutik'),
    'nouveau': ('inventaire', 'Produit ajouté dans Ma Boutik'),
}
MAX_EVENEMENTS = 200


def empreinte(cle):
    return hashlib.sha256((cle or '').encode()).hexdigest()


def nouvelle_cle(boutique):
    """Crée (ou remplace) la clé : renvoyée en clair une seule fois."""
    cle = f'lp{boutique.id}_' + secrets.token_urlsafe(24)
    boutique.cle_synchro = empreinte(cle)
    db.session.commit()
    return cle


def boutique_de_la_cle(cle):
    """La boutique de cette clé (comparaison sûre), ou None."""
    if not cle or not cle.startswith('lp') or '_' not in cle:
        return None
    try:
        bid = int(cle[2:cle.index('_')])
    except ValueError:
        return None
    b = db.session.get(Boutique, bid)
    if b and b.cle_synchro and hmac.compare_digest(b.cle_synchro, empreinte(cle)):
        return b
    return None


def _article(boutique_id, nom):
    nom = (nom or '').strip().lower()
    if not nom:
        return None
    return Article.query.filter(Article.boutique_id == boutique_id, db.func.lower(db.func.trim(Article.nom)) == nom).first()


def _nombre(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def appliquer(boutique, evenements):
    """Applique une liste de mouvements. Renvoie {ref: statut}."""
    res = {}
    for e in (evenements or [])[:MAX_EVENEMENTS]:
        if not isinstance(e, dict):
            continue
        ref = str(e.get('ref') or '')[:80]
        type_ = e.get('type')
        if not ref or type_ not in TYPES:
            continue
        if SynchroMaBoutik.query.filter_by(boutique_id=boutique.id, ref=ref).first():
            res[ref] = 'deja'
            continue
        produit = (e.get('produit') or '').strip()[:200]
        try:
            delta = int(e.get('delta') or 0)
        except (TypeError, ValueError):
            delta = 0
        article = _article(boutique.id, produit) or (_article(boutique.id, e.get('ancien_nom')) if e.get('ancien_nom') else None)
        statut, note = 'applique', None
        if type_ == 'nouveau' and article is None and produit:
            article = Article(boutique_id=boutique.id, nom=produit, prix=_nombre(e.get('prix_vente')) or 0,
                              prix_achat=_nombre(e.get('prix_achat')) or None,
                              categorie=(e.get('categorie') or '').strip()[:60] or None, en_ligne=False, photos_urls=[])
            enregistrer_avec_numero(article, 'numero', Article.prochain_numero)
            article.stock = 0
            delta = int(_nombre(e.get('stock')) or 0)
            note = 'article créé (caché du catalogue)'
        if article is None:
            statut = 'inconnu'
        elif article.suit_variantes:
            statut, note = 'inconnu', 'article suivi par taille / couleur : ajustez à la main'
        else:
            if e.get('ancien_nom') and article.nom.strip().lower() != produit.lower() and produit \
                    and not _article(boutique.id, produit):
                note = f'renommé (avant : {article.nom})'
                article.nom = produit
            if delta:
                if article.stock is None:
                    article.stock = 0
                type_mvt, libelle = TYPES[type_]
                stock.mouvement(article, delta, type_mvt, note=libelle + (f" ({e.get('par')})" if e.get('par') else ''))
        db.session.add(SynchroMaBoutik(boutique_id=boutique.id, ref=ref, type=type_, produit=produit or '?', delta=delta,
                                       statut=statut, note=note, article_id=article.id if article else None,
                                       date_maboutik=(e.get('quand') or '')[:20] or None))
        db.session.commit()
        res[ref] = statut
    boutique.derniere_synchro = datetime.utcnow()
    db.session.commit()
    return res
