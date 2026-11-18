"""Vente directe au comptoir (comme une caisse de supermarché).

Une vente au comptoir est enregistrée comme une commande « Comptoir » déjà livrée :
le stock baisse tout de suite (bonne variante), l'argent entre en caisse, et tout le reste
de LivraPlus marche aussitôt (historique, fiche client, retours, statistiques…).

Codes-barres : celui de l'article (Article.code_barre) ou celui d'une variante
(Article.variantes[clé]['cb']), lus par une douchette (elle « tape » le code puis Entrée)
ou par la caméra du téléphone. Sans code d'usine, la boutique peut créer un code interne
(EAN-13 commençant par 2, réservé à l'usage en magasin) et imprimer l'étiquette."""
import random
import re

import stock
from models import db, Article, Commande, enregistrer_avec_numero

MODES_PAIEMENT = {
    'especes': ('Espèces', 'fa-money-bill-wave'),
    'tmoney': ('T-Money', 'fa-mobile-screen'),
    'flooz': ('Flooz', 'fa-mobile-screen'),
    'carte': ('Carte', 'fa-credit-card'),
    'autre': ('Autre', 'fa-ellipsis'),
}
CODE_RE = re.compile(r'^[0-9A-Za-z\-\.\/ ]{3,40}$')


def propre(code):
    """Code-barres nettoyé (espaces retirés), ou None s'il est invalide."""
    code = (code or '').strip().replace(' ', '')
    return code if code and CODE_RE.match(code) else None


def cle_ean13(douze):
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(douze))
    return str((10 - total % 10) % 10)


def code_interne(boutique_id):
    """Nouveau code EAN-13 interne (préfixe 2 = usage en magasin), unique dans la boutique."""
    for _ in range(50):
        douze = '2' + f'{boutique_id % 1000:03d}' + f'{random.randint(0, 99999999):08d}'
        code = douze + cle_ean13(douze)
        if not trouver(boutique_id, code)[0]:
            return code
    raise RuntimeError('Impossible de créer un code unique')


def trouver(boutique_id, code):
    """(article, clé de variante ou None) correspondant à ce code-barres, sinon (None, None)."""
    code = propre(code)
    if not code:
        return None, None
    article = Article.query.filter_by(boutique_id=boutique_id, code_barre=code, archive=False).first()
    if article:
        return article, None
    for a in Article.query.filter(Article.boutique_id == boutique_id, Article.archive.is_(False),
                                  Article.variantes.isnot(None)).all():
        for cle, v in (a.variantes or {}).items():
            if (v or {}).get('cb') == code and cle in dict(a.combinaisons()):
                return a, cle
    return None, None


def deja_pris(boutique_id, code, article_id=None, cle=None):
    """Ce code est-il déjà utilisé par un AUTRE article ou une autre variante ? Renvoie son nom, ou None."""
    a, c = trouver(boutique_id, code)
    if a is None or (a.id == article_id and c == cle):
        return None
    return a.nom + (f' ({a.libelle_cle(c)})' if c else '')


JOURS_PLUS_VENDUS = 60


def ventes_recentes(boutique_id, jours=JOURS_PLUS_VENDUS):
    """{article_id: pièces vendues} sur les derniers jours (comptoir et commandes livrées)."""
    from datetime import datetime, timedelta
    depuis = datetime.utcnow() - timedelta(days=jours)
    res = {}
    for (lignes,) in (db.session.query(Commande.articles_json)
                      .filter(Commande.boutique_id == boutique_id, Commande.statut.in_(('livree', 'retournee')),
                              Commande.date_commande >= depuis).all()):
        for l in lignes or []:
            if l.get('article_id'):
                res[l['article_id']] = res.get(l['article_id'], 0) + int(l.get('quantite') or 0)
    return res


def catalogue_caisse(boutique_id):
    """Articles pour la page « Vendre » (recherche et lecture des codes sur le téléphone, sans attendre)."""
    reserves = stock.reserves(boutique_id)
    vendus = ventes_recentes(boutique_id)
    res = []
    for a in (Article.query.filter_by(boutique_id=boutique_id, archive=False)
              .order_by(Article.numero).all()):
        photos = [p for p in (a.photos_urls or []) if p]
        v = {}
        for cle, choisis in a.combinaisons():
            e = (a.variantes or {}).get(cle) or {}
            v[cle] = {'l': a.libelle_choix(choisis), 'p': a.prix_de(cle),
                      's': a.stock_variante(cle) if a.suit_variantes else None,
                      'r': reserves.get((a.id, cle), 0), 'cb': e.get('cb')}
        res.append({'id': a.id, 'n': a.numero, 'nom': a.nom, 'cat': a.categorie or '', 'prix': a.prix, 'photo': photos[0] if photos else None,
                    'vd': vendus.get(a.id, 0),
                    'cb': a.code_barre, 's': a.stock, 'r': reserves.get((a.id, None), 0),
                    'options': a.options or {}, 'suivi': a.suit_variantes, 'v': v,
                    'photos': a.photos_valeurs() if a.options else {}, 'tout': photos})
    return res


def vendre(boutique, lignes, remise=0, mode='especes', recu=None, client_nom='', client_tel='', par=None, paye=None):
    """Enregistre la vente. lignes : [{'article_id', 'cle' (variante ou None), 'quantite'}].
    paye : vente à crédit, somme payée maintenant (le reste devient une créance au nom du client).
    Renvoie (commande, None) ou (None, message d'erreur)."""
    if not lignes:
        return None, 'Le panier est vide'
    if mode not in MODES_PAIEMENT:
        mode = 'especes'
    articles_json, besoin = [], {}
    for l in lignes:
        try:
            article_id, quantite = int(l.get('article_id')), int(l.get('quantite') or 0)
        except (TypeError, ValueError):
            return None, 'Ligne de panier invalide'
        article = db.session.get(Article, article_id)
        if not article or article.boutique_id != boutique.id or article.archive:
            return None, 'Un article du panier n\'est plus en vente'
        if quantite < 1 or quantite > 9999:
            return None, f'« {article.nom} » : quantité invalide'
        cle = l.get('cle') or None
        if article.options:
            if not cle or cle not in dict(article.combinaisons()):
                return None, f'« {article.nom} » : choisissez la taille / couleur'
        else:
            cle = None
        choix = article.libelle_cle(cle) if cle else None
        photos = [p for p in (article.photos_urls or []) if p]
        index_photo = 0
        if cle:
            pv = article.photos_valeurs()
            for option, valeur in article.choix_de_cle(cle).items():
                if pv.get(option, {}).get(valeur) is not None:
                    index_photo = pv[option][valeur]
                    break
        articles_json.append({
            'nom': article.nom + (f' ({choix})' if choix else ''), 'options': choix, 'variante': cle,
            'prix': article.prix_de(cle), 'quantite': quantite, 'article_id': article.id, 'numero': article.numero,
            'photo': photos[index_photo] if photos else None, 'pa': article.prix_achat,
        })
        # Stock physique (ce que la boutique a en main) : on ne vend pas ce qu'on n'a pas
        k = (article.id, cle if article.suit_variantes else None)
        besoin[k] = besoin.get(k, 0) + quantite
    for (article_id, cle), q in besoin.items():
        article = db.session.get(Article, article_id)
        if article.stock is None:
            continue
        en_main = article.stock_variante(cle) if cle else article.stock
        if q > en_main:
            nom = article.nom + (f' ({article.libelle_cle(cle)})' if cle else '')
            return None, (f'« {nom} » : il n\'en reste que {max(en_main, 0)} en stock' if en_main > 0
                          else f'« {nom} » : épuisé dans votre stock (faites une entrée de stock s\'il est là)')
    sous_total = sum(x['prix'] * x['quantite'] for x in articles_json)
    try:
        remise = max(0.0, min(float(remise or 0), sous_total))
    except (TypeError, ValueError):
        remise = 0.0
    total = round(sous_total - remise, 2)
    try:
        recu = float(recu) if recu not in (None, '') else None
    except (TypeError, ValueError):
        recu = None
    credit = paye not in (None, '')
    if credit:
        try:
            paye = round(max(0.0, min(float(paye), total)), 2)
        except (TypeError, ValueError):
            return None, 'Montant payé invalide'
        if paye >= total - 0.001:
            credit, paye = False, None                      # tout est payé : vente normale
        elif not (client_nom or '').strip() or len(''.join(c for c in (client_tel or '') if c.isdigit())) < 8:
            return None, 'Vente à crédit : le nom et le téléphone du client sont obligatoires (pour le relancer)'
        recu = None
    if not credit and mode == 'especes' and recu is not None and recu + 0.001 < total:
        return None, 'La somme reçue est inférieure au total'
    commande = Commande(
        boutique_id=boutique.id, client_nom=(client_nom or '').strip()[:100] or 'Client comptoir',
        client_telephone=(client_tel or '').strip()[:50], client_adresse='Vente au comptoir',
        articles_json=articles_json, total=total, remise=remise, frais_livraison=0, source='comptoir',
        statut='confirmee', saisie_par=(par or '')[:120] or None, confirmee_par=(par or '')[:120] or None,
        mode_paiement=mode, montant_recu=recu if mode == 'especes' else None, livre_par='boutique', lu=True,
        montant_paye=paye if credit else total, reste_du=round(total - paye, 2) if credit else 0,
    )
    enregistrer_avec_numero(commande, 'numero_commande', Commande.prochain_numero)
    stock.changer_statut(commande, 'livree')       # stock sorti + argent en caisse (vente directe)
    db.session.commit()
    return commande, None


def benefice(commande):
    """Bénéfice de la vente (si les prix d'achat sont connus), sinon None."""
    if any(l.get('pa') is None for l in commande.articles_json):
        return None
    return round(commande.net_articles - sum(l['pa'] * l['quantite'] for l in commande.articles_json), 2)
