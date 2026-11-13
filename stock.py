"""Stock des articles : toute variation passe par ici et laisse une trace
(MouvementStock). Le stock baisse quand une commande est LIVRÉE ; il est
remis si cette livraison est annulée, et augmente lors d'un retour client."""
from datetime import datetime

import caisse
from models import db, Article, MouvementStock, Commande, CodePromo


def article_de_ligne(ligne, boutique_id):
    """Article du catalogue correspondant à une ligne de commande
    (par identifiant, ou par nom pour les commandes plus anciennes)."""
    if ligne.get('article_id'):
        article = db.session.get(Article, ligne['article_id'])
        return article if article and article.boutique_id == boutique_id else None
    return Article.query.filter_by(boutique_id=boutique_id, nom=ligne.get('nom')).first()


def variante_de_ligne(article, ligne):
    """Clé de la variante d'une ligne de commande (ou de retour), si l'article suit ses variantes."""
    if article is None or not article.suit_variantes:
        return None
    cle = ligne.get('variante')
    if cle and cle in dict(article.combinaisons()):
        return cle
    return article.cle_depuis_texte(ligne.get('options'))


def mouvement(article, quantite, type_mouvement, commande=None, note=None, variante=None):
    """Applique +quantite / -quantite au stock d'un article suivi (et de sa variante)."""
    if article is None or article.stock is None or not quantite:
        return
    libelle = stock_var = None
    if variante and article.suit_variantes:
        tableau = {c: dict(v) for c, v in (article.variantes or {}).items()}   # copie : SQLAlchemy voit le changement
        e = tableau.setdefault(variante, {})
        e['stock'] = int(e.get('stock') or 0) + quantite
        article.variantes = tableau
        article.recalculer_stock()
        libelle, stock_var = article.libelle_cle(variante), e['stock']
    else:
        article.stock += quantite
    db.session.add(MouvementStock(
        boutique_id=article.boutique_id, article=article, commande=commande, type=type_mouvement,
        quantite=quantite, stock_apres=article.stock, note=(note or '')[:255] or None,
        variante=(libelle or '')[:150] or None, stock_variante_apres=stock_var,
    ))


def mouvement_ligne(ligne, boutique_id, quantite, type_mouvement, commande=None, note=None):
    """Mouvement de stock pour une ligne de commande (bonne variante comprise)."""
    article = article_de_ligne(ligne, boutique_id)
    mouvement(article, quantite, type_mouvement, commande, note, variante_de_ligne(article, ligne))


def regler_variantes(article, nouveaux, type_mouvement, note):
    """Fixe le stock de chaque variante ({clé: quantité}) en traçant chaque écart.
    Les variantes qui n'existent plus sont vidées (trace aussi)."""
    if not article.suit_variantes:
        # Début du suivi par variante : l'ancien total est remplacé par le détail
        ancien = article.stock
        article.stock_par_variante = True
        article.variantes = {c: {k: x for k, x in v.items() if k != 'stock'} for c, v in (article.variantes or {}).items()}
        if ancien:
            article.stock = ancien
            mouvement(article, -ancien, 'inventaire', note=f'Stock détaillé par variante (ancien total : {ancien})')
        article.stock = 0
    existantes = dict(article.combinaisons())
    tableau = {c: dict(v) for c, v in (article.variantes or {}).items()}
    for cle in list(tableau):
        if cle not in existantes:
            reste = int(tableau[cle].get('stock') or 0)
            if reste:
                article.stock -= reste
                db.session.add(MouvementStock(
                    boutique_id=article.boutique_id, article=article, type='inventaire', quantite=-reste,
                    stock_apres=article.stock, note='Variante retirée de l\'article',
                    variante=cle.replace('|', ', ').replace('=', ' ')[:150], stock_variante_apres=0))
            del tableau[cle]
    article.variantes = tableau
    article.recalculer_stock()
    for cle in existantes:
        if cle not in nouveaux:
            continue
        ecart = int(nouveaux[cle]) - article.stock_variante(cle)
        if ecart:
            mouvement(article, ecart, type_mouvement, note=note, variante=cle)


def _sortir_stock(commande):
    for ligne in commande.articles_json:
        mouvement_ligne(ligne, commande.boutique_id, -int(ligne['quantite']), 'vente',
                        commande, f'Commande n°{commande.numero}')
    commande.stock_deduit = True


def _remettre_stock(commande):
    for ligne in commande.articles_json:
        mouvement_ligne(ligne, commande.boutique_id, int(ligne['quantite']), 'annulation',
                        commande, f'Commande n°{commande.numero} : livraison annulée')
    commande.stock_deduit = False


# Commandes pas encore livrées : leurs articles sont « réservés » (le stock ne baisse qu'à la livraison)
STATUTS_EN_COURS = ('nouvelle', 'confirmee', 'en_livraison', 'echec')

# Changements de statut permis depuis chaque statut (le reste est refusé, même depuis une page restée ouverte)
TRANSITIONS = {
    'nouvelle': {'confirmee', 'livree', 'annulee'},
    'confirmee': {'livree', 'annulee'},
    'en_livraison': {'livree', 'echec', 'annulee', 'confirmee'},
    'echec': {'livree', 'annulee', 'confirmee'},
    'livree': {'en_livraison', 'confirmee', 'annulee'},   # erreur : finalement pas livrée (conditions ci-dessous)
    'retournee': set(),
    'annulee': set(),
}


def refus_transition(commande, statut):
    """Message expliquant pourquoi ce changement de statut est refusé (None = permis)."""
    if statut == commande.statut:
        return None
    if statut not in TRANSITIONS.get(commande.statut, set()):
        return (f"Impossible de passer la commande n°{commande.numero} de « {commande.statut_libelle} » "
                f"à « {Commande.STATUTS.get(statut, (statut,))[0]} ».")
    if commande.statut == 'livree':
        if commande.retours:
            return (f"La commande n°{commande.numero} a déjà un retour d'articles : elle ne peut plus être annulée. "
                    "Utilisez « Retour / échange » pour le reste.")
        if commande.livree_par_livreur and not commande.garde_frais and commande.frais_payes:
            return (f"Les frais de livraison de la commande n°{commande.numero} ont déjà été payés au livreur : "
                    "réglez d'abord cela avec lui (Caisse) avant d'annuler la livraison.")
    return None


def reserves(boutique_id, exclure=None, avant=None):
    """Quantités réservées par les commandes en cours :
    {(article_id, None): total de l'article, (article_id, clé de variante): quantité de la variante}."""
    res = {}
    for c in Commande.query.filter(Commande.boutique_id == boutique_id, Commande.statut.in_(STATUTS_EN_COURS),
                                   Commande.stock_deduit.is_(False)).all():
        if (exclure is not None and c.id == exclure) or (avant is not None and c.id >= avant):
            continue
        for l in c.articles_json or []:
            if not l.get('article_id'):
                continue
            q = int(l.get('quantite') or 0)
            res[(l['article_id'], None)] = res.get((l['article_id'], None), 0) + q
            if l.get('variante'):
                res[(l['article_id'], l['variante'])] = res.get((l['article_id'], l['variante']), 0) + q
    return res


def disponible(article, variante=None, res=None):
    """Ce qui peut encore être vendu : stock moins les commandes en cours (None = stock non suivi)."""
    if article is None or article.stock is None:
        return None
    res = reserves(article.boutique_id) if res is None else res
    if variante and article.suit_variantes:
        return article.stock_variante(variante) - res.get((article.id, variante), 0)
    return article.stock - res.get((article.id, None), 0)


def manques(commande):
    """Lignes d'une commande en cours qui dépassent le stock encore disponible :
    [{'nom', 'demande', 'disponible'}] (les autres commandes en cours passent avant)."""
    if commande.statut not in STATUTS_EN_COURS or commande.stock_deduit:
        return []
    res = reserves(commande.boutique_id, avant=commande.id)   # seules les commandes plus anciennes passent avant
    besoins = {}
    for l in commande.articles_json or []:
        if l.get('article_id'):
            cle = (l['article_id'], l.get('variante'))
            besoins.setdefault(cle, {'nom': l['nom'], 'demande': 0})['demande'] += int(l.get('quantite') or 0)
    resultat = []
    for (article_id, variante), b in besoins.items():
        article = db.session.get(Article, article_id)
        dispo = disponible(article, variante, res)
        if dispo is not None and b['demande'] > dispo:
            resultat.append({'nom': b['nom'], 'demande': b['demande'], 'disponible': max(dispo, 0)})
    return resultat


def _rendre_code_promo(commande):
    """Commande annulée : l'utilisation de son code promo est rendue."""
    from promos import CODE_FIDELITE
    if commande.code_promo and commande.code_promo != CODE_FIDELITE:
        promo = CodePromo.query.filter_by(boutique_id=commande.boutique_id, code=commande.code_promo).first()
        if promo and promo.utilisations:
            promo.utilisations -= 1


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
    if statut == 'annulee' and commande.statut != 'annulee':
        _rendre_code_promo(commande)
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


def confier(commande, livreur):
    """La commande part en livraison avec ce livreur (il passe la récupérer à la boutique)."""
    from models import nouveau_code_lien
    commande.livreur = livreur
    commande.proposee_at = None
    if not commande.code_livraison:
        commande.code_livraison = nouveau_code_lien()
    changer_statut(commande, 'en_livraison')
    commande.lu = True
