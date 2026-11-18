"""Créances : ventes au comptoir à crédit (le client paie une partie, le reste plus tard).

  - commande.montant_paye : ce que le client a déjà payé (cumul) ;
  - commande.reste_du     : ce qu'il doit encore ;
  - chaque remboursement est un PaiementCreance. Encaissé par le gérant / caissier : validé tout
    de suite (l'argent entre en caisse). Encaissé par un vendeur : en attente de validation,
    comme dans Ma Boutik (le gérant voit ce que le vendeur dit avoir reçu avant de le compter)."""
from datetime import datetime

import caisse
import comptoir
import messages_whatsapp as msg
from models import db, Commande, PaiementCreance


def ouvertes(boutique_id):
    return (Commande.query.filter(Commande.boutique_id == boutique_id, Commande.reste_du > 0.001,
                                  Commande.statut.in_(('livree', 'retournee')))
            .order_by(Commande.date_commande).all())


def en_attente(boutique_id):
    return (PaiementCreance.query.filter_by(boutique_id=boutique_id, statut='en_attente')
            .order_by(PaiementCreance.date).all())


def total_du(boutique_id):
    return round(sum(c.reste_du for c in ouvertes(boutique_id)), 2)


def attente_sur(commande):
    """Montant déjà annoncé par un vendeur pour cette créance, pas encore validé."""
    return sum(p.montant for p in commande.paiements_creance if p.statut == 'en_attente')


def payer(commande, montant, mode, par, valider_tout_de_suite):
    """Enregistre un remboursement. Renvoie (paiement, None) ou (None, erreur)."""
    try:
        montant = round(float(montant), 2)
    except (TypeError, ValueError):
        return None, 'Montant invalide'
    if montant <= 0:
        return None, 'Montant invalide'
    possible = round((commande.reste_du or 0) - attente_sur(commande), 2)
    if montant > possible + 0.001:
        return None, (f'Le montant dépasse ce qui reste à payer ({msg.fcfa(max(possible, 0))}'
                      + (', une partie attend déjà la validation du gérant' if attente_sur(commande) else '') + ')')
    p = PaiementCreance(boutique_id=commande.boutique_id, commande=commande, montant=montant,
                        mode=mode if mode in comptoir.MODES_PAIEMENT else 'especes', par=(par or '')[:120],
                        statut='en_attente')
    db.session.add(p)
    if valider_tout_de_suite:
        _appliquer(p, par)
    db.session.commit()
    return p, None


def _appliquer(p, par):
    c = p.commande
    p.statut, p.valide_par, p.date_validation = 'valide', (par or '')[:120], datetime.utcnow()
    c.montant_paye = round((c.montant_paye or 0) + p.montant, 2)
    c.reste_du = round(max(0.0, (c.reste_du or 0) - p.montant), 2)
    if c.reste_du <= 0.001:
        c.reste_du, c.reglee, c.date_reglement = 0, True, datetime.utcnow()
    caisse.ajouter(c.boutique_id, 'creance', p.montant,
                   f'Paiement de créance : {c.client_nom} (vente n°{c.numero})'
                   + (f' · reste {msg.fcfa(c.reste_du)}' if c.reste_du else ' · soldée'),
                   commande_id=c.id)


def valider(p, par):
    if p.statut != 'en_attente':
        return 'Ce paiement a déjà été traité'
    if p.montant > (p.commande.reste_du or 0) + 0.001:
        return 'Ce paiement dépasse ce qui reste à payer'
    _appliquer(p, par)
    db.session.commit()
    return None


def refuser(p, par, motif):
    if p.statut != 'en_attente':
        return 'Ce paiement a déjà été traité'
    p.statut, p.valide_par, p.date_validation = 'refuse', (par or '')[:120], datetime.utcnow()
    p.motif_refus = (motif or '').strip()[:200] or None
    db.session.commit()
    return None


def appliquer_retour(commande, montant):
    """Articles rendus sur une vente à crédit : la dette baisse d'abord.
    Renvoie ce qu'il faut vraiment rembourser en argent."""
    du = commande.reste_du or 0
    if du <= 0:
        return montant
    efface = min(du, montant)
    commande.reste_du = round(du - efface, 2)
    if commande.reste_du <= 0.001:
        commande.reste_du, commande.reglee = 0, True
    return round(montant - efface, 2)


def message_relance(commande):
    b = commande.boutique
    return (f"Bonjour {commande.client_nom} 👋\nC'est {b.nom_boutique}. Petit rappel : il reste *{msg.fcfa(commande.reste_du)}* "
            f"à régler sur votre achat du {commande.date_commande.strftime('%d/%m/%Y')} (ticket n°{commande.numero}, "
            f"total {msg.fcfa(commande.total)}, déjà payé {msg.fcfa(commande.montant_paye or 0)}).\n"
            "Vous pouvez passer en boutique ou payer par T-Money / Flooz. Merci ! 🙏")
