"""Import d'une boutique de Ma Boutik (fichier JSON produit par exporter_unik.py) dans LivraPlus.

  - articles : nom, catégorie, prix de vente, prix d'achat (0 = inconnu), stock (tracé « Import Ma Boutik ») ;
    ils arrivent CACHÉS du catalogue en ligne (pas encore de photo) mais vendables au comptoir ;
    un article qui existe déjà (même nom) n'est pas recréé : il est simplement compté « déjà présent ».
  - créances ouvertes : reprises comme ventes au comptoir à crédit (reste dû, payé), sans toucher
    au stock ni à la caisse (l'argent déjà payé est dans l'ancienne caisse) ; jamais en double.
Rien n'est écrit tant que l'administrateur n'a pas confirmé l'aperçu."""
import json
from datetime import datetime

import stock
from models import db, Article, Commande, enregistrer_avec_numero

ADRESSE_CREANCE = 'Créance reprise de Ma Boutik'


def lire(texte):
    """Contrôle le fichier. Renvoie (données, None) ou (None, erreur)."""
    try:
        d = json.loads(texte)
    except (ValueError, TypeError):
        return None, "Ce fichier n'est pas un export Ma Boutik valide (JSON illisible)."
    if not isinstance(d, dict) or d.get('source') != 'Ma Boutik' or not isinstance(d.get('articles'), list):
        return None, "Ce fichier n'est pas un export Ma Boutik."
    return d, None


def _prix(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def apercu(d, boutique):
    existants = {a.nom.strip().lower() for a in Article.query.filter_by(boutique_id=boutique.id).all()}
    nouveaux = [a for a in d['articles'] if a.get('nom', '').strip().lower() not in existants]
    deja = len(d['articles']) - len(nouveaux)
    creances = [c for c in d.get('creances') or [] if not _creance_existe(boutique, c)]
    return {'boutique': d.get('boutique'), 'exporte_le': d.get('exporte_le'), 'articles': len(d['articles']),
            'nouveaux': nouveaux, 'deja': deja, 'pieces': sum(int(a.get('stock') or 0) for a in nouveaux),
            'sans_prix_achat': sum(1 for a in nouveaux if not _prix(a.get('prix_achat'))),
            'creances': creances, 'total_creances': sum(float(c.get('reste') or 0) for c in creances),
            'categories': sorted({a.get('categorie') for a in nouveaux if a.get('categorie')})}


def _creance_existe(boutique, c):
    return Commande.query.filter_by(boutique_id=boutique.id, client_adresse=ADRESSE_CREANCE,
                                    client_nom=(c.get('client_nom') or 'Client')[:100],
                                    total=float(c.get('total') or 0)).first() is not None


def _date(texte):
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime((texte or '').strip()[:10], fmt)
        except ValueError:
            pass
    return datetime.utcnow()


def importer(d, boutique):
    """Écrit les articles et les créances. Renvoie le bilan."""
    a = apercu(d, boutique)
    crees = 0
    for x in a['nouveaux']:
        article = Article(boutique_id=boutique.id, nom=x['nom'].strip()[:200], prix=float(x.get('prix_vente') or 0),
                          prix_achat=_prix(x.get('prix_achat')), categorie=(x.get('categorie') or '').strip()[:60] or None,
                          en_ligne=False, photos_urls=[])
        enregistrer_avec_numero(article, 'numero', Article.prochain_numero)
        qte = int(x.get('stock') or 0)
        article.stock = 0
        if qte > 0:
            stock.mouvement(article, qte, 'inventaire', note='Import Ma Boutik (stock du ' + (d.get('exporte_le') or '') + ')')
        crees += 1
    db.session.commit()
    reprises = 0
    for c in a['creances']:
        quand = _date(c.get('date'))
        total, paye, reste = float(c.get('total') or 0), float(c.get('paye') or 0), float(c.get('reste') or 0)
        commande = Commande(
            boutique_id=boutique.id, client_nom=(c.get('client_nom') or 'Client')[:100],
            client_telephone=(c.get('client_telephone') or '')[:50], client_adresse=ADRESSE_CREANCE,
            articles_json=[{'nom': f"Achat à crédit du {quand.strftime('%d/%m/%Y')} (repris de Ma Boutik)",
                            'prix': total, 'quantite': 1}],
            total=total, remise=0, frais_livraison=0, source='comptoir', statut='livree', lu=True,
            date_commande=quand, date_livraison=quand, stock_deduit=True, livre_par='boutique',
            montant_paye=paye, reste_du=reste, reglee=False, saisie_par=(c.get('vendeur') or '')[:120] or None,
            instructions='Créance reprise de Ma Boutik : le déjà payé était dans la caisse de Ma Boutik.')
        enregistrer_avec_numero(commande, 'numero_commande', Commande.prochain_numero)
        reprises += 1
    return {'articles': crees, 'deja': a['deja'], 'pieces': a['pieces'], 'creances': reprises,
            'total_creances': a['total_creances']}
