"""Codes promo : réduction en pourcentage ou en montant sur le prix des articles
(jamais sur les frais de livraison, qui reviennent au livreur)."""
from datetime import datetime

from models import CodePromo


def normaliser_code(code):
    return ''.join(c for c in (code or '').upper() if c.isalnum() or c in '-_')[:30]


def verifier(boutique_id, code, sous_total):
    """(code_promo, remise, erreur) : erreur est un message lisible si le code ne s'applique pas."""
    code = normaliser_code(code)
    if not code:
        return None, 0, None
    promo = CodePromo.query.filter_by(boutique_id=boutique_id, code=code).first()
    if not promo or not promo.actif:
        return None, 0, "Ce code promo n'existe pas ou n'est plus valable."
    if promo.date_fin and datetime.utcnow().date() > promo.date_fin:
        return None, 0, 'Ce code promo a expiré.'
    if promo.utilisations_max and promo.utilisations >= promo.utilisations_max:
        return None, 0, "Ce code promo a atteint son nombre maximum d'utilisations."
    if promo.minimum and sous_total < promo.minimum:
        return None, 0, f"Ce code est valable dès {promo.minimum:,.0f} FCFA d'achat.".replace(',', ' ')
    if promo.type == 'pourcentage':
        remise = round(sous_total * promo.valeur / 100)
    else:
        remise = promo.valeur
    return promo, min(remise, sous_total), None
