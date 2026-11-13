"""Codes promo : réduction en pourcentage ou en montant sur le prix des articles
(jamais sur les frais de livraison, qui reviennent au livreur)."""
from datetime import datetime

from models import db, CodePromo, Commande

CODE_FIDELITE = 'FIDELITE'


def normaliser_code(code):
    return ''.join(c for c in (code or '').upper() if c.isalnum() or c in '-_')[:30]


def verifier(boutique_id, code, sous_total, nb_articles=None, telephone=None):
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
    if promo.une_fois_par_client and telephone and len(cle_telephone(telephone)) >= 8:
        cle = cle_telephone(telephone)
        deja = Commande.query.with_entities(Commande.client_telephone).filter(
            Commande.boutique_id == boutique_id, Commande.code_promo == promo.code, Commande.statut != 'annulee').all()
        if any(cle_telephone(t) == cle for (t,) in deja):
            return None, 0, 'Vous avez déjà utilisé ce code promo (valable une seule fois par client).'
    if promo.min_articles and nb_articles is not None and nb_articles < promo.min_articles:
        return None, 0, f"Ce code est valable dès {promo.min_articles} articles dans la commande."
    if promo.minimum and sous_total < promo.minimum:
        return None, 0, f"Ce code est valable dès {promo.minimum:,.0f} FCFA d'achat.".replace(',', ' ')
    if promo.type == 'pourcentage':
        remise = round(sous_total * promo.valeur / 100)
    else:
        remise = promo.valeur
    return promo, min(remise, sous_total), None


def cle_telephone(numero):
    chiffres = ''.join(c for c in (numero or '') if c.isdigit())
    return chiffres[-8:] if len(chiffres) >= 8 else chiffres


def regle_fidelite(boutique):
    """Phrase lisible de la règle, ou None si la fidélité n'est pas active."""
    if not boutique.fidelite_actif or not boutique.fidelite_seuil or not boutique.fidelite_valeur:
        return None
    valeur = (f'{boutique.fidelite_valeur:g} %' if boutique.fidelite_type != 'montant'
              else f'{boutique.fidelite_valeur:,.0f} FCFA'.replace(',', ' '))
    n = boutique.fidelite_seuil
    if boutique.fidelite_mode == 'palier':
        texte = f'-{valeur} sur une commande toutes les {n} commandes livrées'
    else:
        texte = f'-{valeur} sur chaque commande dès {n} commande{"s" if n > 1 else ""} livrée{"s" if n > 1 else ""}'
    if boutique.fidelite_minimum:
        texte += f' (achat minimum {boutique.fidelite_minimum:,.0f} FCFA)'.replace(',', ' ')
    return texte


def fidelite(boutique, telephone, sous_total):
    """Réduction de fidélité pour ce client : {'remise', 'livrees', 'restant', 'regle'}.
    Le client est reconnu par les 8 derniers chiffres de son numéro ; seules ses
    commandes LIVRÉES dans cette boutique comptent."""
    regle = regle_fidelite(boutique)
    cle = cle_telephone(telephone)
    if not regle or len(cle) < 8:
        return {'remise': 0, 'livrees': 0, 'restant': None, 'regle': regle, 'en_attente': 0}
    lignes = [(statut, code) for (t, statut, code) in Commande.query.with_entities(
        Commande.client_telephone, Commande.statut, Commande.code_promo).filter(
        Commande.boutique_id == boutique.id, Commande.statut != 'annulee').all() if cle_telephone(t) == cle]
    livrees = sum(1 for statut, _ in lignes if statut == 'livree')
    # Réductions fidélité déjà accordées (livrées ou en cours) : on ne les redonne pas
    utilisees = sum(1 for _, code in lignes if code == CODE_FIDELITE)
    en_attente = sum(1 for statut, code in lignes if code == CODE_FIDELITE and statut in ('nouvelle', 'confirmee', 'en_livraison', 'echec'))
    seuil = boutique.fidelite_seuil
    if boutique.fidelite_mode == 'palier':
        # 1 réduction gagnée à chaque palier atteint (5, 10, 15… livrées), utilisable une fois
        droit = livrees // seuil > utilisees
        restant = 0 if droit else seuil - (livrees % seuil)
    else:
        # Dès le seuil, sur chaque commande… une à la fois (la suivante après livraison de celle en cours)
        droit = livrees >= seuil and not en_attente
        restant = max(0, seuil - livrees)
    remise = 0
    if droit and sous_total >= (boutique.fidelite_minimum or 0):
        remise = (round(sous_total * boutique.fidelite_valeur / 100) if boutique.fidelite_type != 'montant'
                  else boutique.fidelite_valeur)
        remise = min(remise, sous_total)
    return {'remise': remise, 'livrees': livrees, 'restant': restant, 'regle': regle, 'en_attente': en_attente}


def meilleure_reduction(boutique, telephone, sous_total, code, nb_articles):
    """(promo, code_enregistre, remise, erreur_code) : le code promo OU la réduction de
    fidélité, la plus avantageuse des deux (elles ne se cumulent pas)."""
    promo, remise_code, erreur = verifier(boutique.id, code, sous_total, nb_articles, telephone)
    fid = fidelite(boutique, telephone, sous_total)['remise']
    if fid > remise_code:
        return None, CODE_FIDELITE, fid, erreur
    return promo, (promo.code if promo else None), remise_code, erreur


def consommer(promo):
    """Une utilisation de plus, sans perte si deux commandes arrivent en même temps."""
    if promo:
        db.session.execute(db.update(CodePromo).where(CodePromo.id == promo.id)
                           .values(utilisations=CodePromo.utilisations + 1))
