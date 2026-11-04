"""Abonnement mensuel des boutiques à LivraPlus.

Règles :
- l'administrateur fixe le prix mensuel de chaque boutique et le premier mois facturé ;
  sans prix (ou 0), la boutique n'a rien à payer ;
- chaque mois se paie entre le 1er et le 8 : jaune du 1er au 3, orange du 4 au 6,
  rouge le 7 et le 8 ; après le 8, l'espace boutique est coupé (tableau de bord seulement)
  jusqu'au paiement. Le catalogue des clients et l'espace des livreurs continuent de marcher ;
- le paiement s'enregistre comme une charge « Abonnement logiciel » (montant imposé),
  avec le moyen de paiement, la date et la référence du dépôt (sauf espèces).
"""
from datetime import date, datetime

from models import db, MouvementCaisse, PaiementAbonnement

CATEGORIE = 'Abonnement logiciel'
JOUR_LIMITE = 8
MOIS_FR = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
           'septembre', 'octobre', 'novembre', 'décembre']


def cle_mois(d):
    return f'{d.year:04d}-{d.month:02d}'


def mois_suivant(cle):
    annee, mois = map(int, cle.split('-'))
    return f'{annee + (mois == 12):04d}-{mois % 12 + 1:02d}'


def libelle_mois(cle):
    annee, mois = map(int, cle.split('-'))
    return f'{MOIS_FR[mois - 1]} {annee}'


def premier_mois_par_defaut(aujourdhui=None):
    """Quand l'administrateur fixe un prix : ce mois-ci si on est encore dans la période
    de paiement (1er–8), sinon le mois prochain (pas de coupure surprise)."""
    aujourdhui = aujourdhui or date.today()
    cle = cle_mois(aujourdhui)
    return cle if aujourdhui.day <= JOUR_LIMITE else mois_suivant(cle)


def mois_payes(boutique):
    return {p.mois for p in boutique.paiements_abonnement if p.statut == 'valide'}


def etat(boutique, aujourdhui=None):
    """Situation de l'abonnement, pour l'affichage et le blocage.
    niveau : 'gratuit', 'ok', 'jaune', 'orange', 'rouge' ou 'bloque'."""
    aujourdhui = aujourdhui or date.today()
    mois = cle_mois(aujourdhui)
    prix = boutique.abonnement_prix or 0
    debut = boutique.abonnement_debut
    if not prix or not debut:
        return {'niveau': 'gratuit', 'exige': False, 'bloque': False, 'prix': 0, 'mois_a_payer': None}
    payes = mois_payes(boutique)
    # Mois que le prochain paiement réglera : le premier mois dû non payé (à partir du mois courant)
    a_payer = max(mois, debut)
    while a_payer in payes:
        a_payer = mois_suivant(a_payer)
    res = {'exige': True, 'prix': prix, 'mois_a_payer': a_payer, 'libelle_mois_a_payer': libelle_mois(a_payer),
           'mois_courant_paye': mois in payes or mois < debut, 'jours_restants': None}
    if res['mois_courant_paye']:
        res.update(niveau='ok', bloque=False)
        return res
    jour = aujourdhui.day
    res['jours_restants'] = max(JOUR_LIMITE - jour, 0)
    if jour > JOUR_LIMITE:
        res.update(niveau='bloque', bloque=True)
    elif jour >= 7:
        res.update(niveau='rouge', bloque=False)
    elif jour >= 4:
        res.update(niveau='orange', bloque=False)
    else:
        res.update(niveau='jaune', bloque=False)
    return res


MODES = PaiementAbonnement.MODES


def enregistrer(boutique, mode, reference, date_paiement, par=None):
    """Enregistre le paiement du mois dû. Renvoie (paiement, erreur)."""
    situation = etat(boutique)
    if not situation['exige']:
        return None, "Votre boutique n'a pas d'abonnement à payer."
    if mode not in MODES:
        return None, 'Choisissez le moyen de paiement.'
    reference = (reference or '').strip().upper()[:80]
    if mode != 'especes':
        if len(reference) < 4:
            return None, f'Indiquez la référence du dépôt {MODES[mode]} (au moins 4 caractères).'
        deja = (PaiementAbonnement.query.filter_by(mode=mode, reference=reference, statut='valide').first())
        if deja:
            return None, 'Cette référence de dépôt a déjà été utilisée pour un autre paiement.'
    else:
        reference = None
    if not date_paiement:
        return None, 'Indiquez la date du dépôt.'
    if date_paiement > date.today():
        return None, 'La date du dépôt ne peut pas être dans le futur.'
    if (date.today() - date_paiement).days > 45:
        return None, 'Cette date de dépôt est trop ancienne (plus de 45 jours).'
    mois = situation['mois_a_payer']
    if mois > mois_suivant(cle_mois(date.today())):
        return None, f"L'abonnement est déjà payé jusqu'à {libelle_mois(mois)} exclu. Merci !"

    libelle = f"Abonnement LivraPlus {libelle_mois(mois)} · {MODES[mode]}" + (f" réf. {reference}" if reference else '')
    mouvement = MouvementCaisse(boutique_id=boutique.id, type='charge', categorie=CATEGORIE, libelle=libelle[:200],
                                montant=-situation['prix'], par=par,
                                date=datetime.combine(date_paiement, datetime.utcnow().time()))
    db.session.add(mouvement)
    db.session.flush()
    paiement = PaiementAbonnement(boutique_id=boutique.id, mois=mois, montant=situation['prix'], mode=mode,
                                  reference=reference, date_paiement=date_paiement, par=par, mouvement_id=mouvement.id)
    db.session.add(paiement)
    db.session.commit()
    return paiement, None


def annuler(paiement):
    """Par l'administrateur (référence fausse, dépôt non reçu…) : le mois redevient dû."""
    if paiement.statut != 'valide':
        return
    paiement.statut = 'annule'
    if paiement.mouvement_id:
        mouvement = db.session.get(MouvementCaisse, paiement.mouvement_id)
        if mouvement:
            db.session.delete(mouvement)
        paiement.mouvement_id = None
    db.session.commit()
