"""Classements et répartitions pour la page Statistiques :
articles les plus vendus, livreurs les plus actifs, quartiers où l'on livre le plus,
meilleurs clients, heures et jours de pointe, codes promo, livraison ou retrait."""
import re

from zones_detection import normaliser, zone_pour_adresse

JOURS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
_COUPURES = re.compile(r"[,;\n(]| - | près | pres | derri[eè]re | face | en face | à côté | a cote | non loin ", re.I)


def quartier_de(adresse, zones):
    """Quartier d'une adresse : celui reconnu dans les zones de la boutique, sinon le
    début de l'adresse (le client écrit le quartier d'abord). None pour un retrait."""
    adresse = (adresse or '').strip()
    if not adresse or adresse.lower().startswith('retrait en boutique'):
        return None
    _, reconnu = zone_pour_adresse(adresse, zones)
    if reconnu and len(reconnu) > 2:
        return reconnu.title()
    debut = _COUPURES.split(adresse)[0].strip()
    mots = debut.split()[:3]
    return ' '.join(mots).title() if mots else None


def _cle_tel(telephone):
    chiffres = ''.join(c for c in (telephone or '') if c.isdigit())
    return chiffres[-8:] or telephone


def classements(recues, livrees, echecs, zones):
    """Toutes les répartitions d'une période. `livrees` = commandes livrées sur la période."""
    # Quartiers (livraisons réelles uniquement, pas les retraits)
    quartiers, points = {}, []
    for c in livrees:
        q = quartier_de(c.client_adresse, zones)
        if q:
            g = quartiers.setdefault(normaliser(q), {'nom': q, 'livraisons': 0, 'ventes': 0, 'frais': 0})
            g['livraisons'] += 1
            g['ventes'] += c.net_articles
            g['frais'] += c.frais_livraison or 0
        if c.latitude is not None and c.longitude is not None:
            points.append({'lat': c.latitude, 'lng': c.longitude, 'n': c.numero, 'q': q or ''})
    quartiers = sorted(quartiers.values(), key=lambda g: (-g['livraisons'], -g['ventes']))

    # Meilleurs clients (livrées)
    clients = {}
    for c in sorted(livrees, key=lambda c: c.date_commande):
        g = clients.setdefault(_cle_tel(c.client_telephone), {'nom': c.client_nom, 'telephone': c.client_telephone,
                                                              'commandes': 0, 'montant': 0, 'derniere': c.date_commande})
        g['nom'], g['derniere'] = c.client_nom, c.date_commande
        g['commandes'] += 1
        g['montant'] += c.total
    clients = sorted(clients.values(), key=lambda g: (-g['montant'], -g['commandes']))

    # Heures et jours où les commandes arrivent
    heures = [0] * 24
    jours = [0] * 7
    for c in recues:
        heures[c.date_commande.hour] += 1
        jours[c.date_commande.weekday()] += 1
    heure_pointe = max(range(24), key=lambda h: heures[h]) if any(heures) else None
    jour_pointe = JOURS[max(range(7), key=lambda j: jours[j])] if any(jours) else None

    # Codes promo utilisés (commandes livrées)
    promos = {}
    for c in livrees:
        if c.code_promo:
            g = promos.setdefault(c.code_promo, {'code': c.code_promo, 'commandes': 0, 'remise': 0, 'ventes': 0})
            g['commandes'] += 1
            g['remise'] += c.remise or 0
            g['ventes'] += c.net_articles
    promos = sorted(promos.values(), key=lambda g: -g['commandes'])

    # Livraison ou retrait ; qui a remis la commande
    retraits = sum(1 for c in livrees if c.est_retrait)
    par_boutique = sum(1 for c in livrees if not c.livree_par_livreur and not c.est_retrait)
    preparations = [(c.date_depart - c.date_commande).total_seconds() / 3600 for c in livrees
                    if c.date_depart and c.date_depart >= c.date_commande]
    return {
        'quartiers': quartiers, 'points': points, 'clients': clients[:10], 'nb_clients': len(clients),
        'clients_fideles': sum(1 for g in clients if g['commandes'] > 1),
        'heures': heures, 'jours': jours, 'jours_noms': JOURS, 'heure_pointe': heure_pointe, 'jour_pointe': jour_pointe,
        'promos': promos, 'retraits': retraits, 'livraisons': len(livrees) - retraits, 'par_boutique': par_boutique,
        'preparation': (sum(preparations) / len(preparations)) if preparations else None,
    }
