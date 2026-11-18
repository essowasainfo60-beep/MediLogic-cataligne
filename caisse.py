"""Caisse de la boutique : chaque entrée ou sortie d'argent est un MouvementCaisse
(montant positif = entrée, négatif = sortie) ; le solde est leur somme.

Commande livrée par un livreur (paiement à la livraison) :
  - le livreur encaisse le total chez le client ;
  - l'argent des ARTICLES appartient à la boutique : il entre en caisse quand
    le livreur le remet (« versement ») ;
  - les FRAIS DE LIVRAISON appartiennent au livreur. Choisi pour chaque commande
    en confiant la course (Commande.mode_frais ; à défaut, réglage de la boutique) :
      * 'livreur_garde'    : il les garde, il ne remet que les articles ;
      * 'boutique_collecte' : il remet tout, la boutique le paie ensuite
                              (« paiement livreur »).
Commande livrée sans livreur (retrait en boutique) : l'argent entre directement.
"""
from datetime import datetime

from flask_login import current_user

from models import db, MouvementCaisse


def ajouter(boutique_id, type_mouvement, montant, libelle, categorie=None, livreur_id=None, commande_id=None, date=None):
    db.session.add(MouvementCaisse(
        boutique_id=boutique_id, type=type_mouvement, montant=round(montant, 2), libelle=(libelle or '')[:200],
        categorie=categorie, livreur_id=livreur_id, commande_id=commande_id, date=date or datetime.utcnow(),
        par=getattr(current_user, 'nom_utilisateur', None) if current_user and current_user.is_authenticated else None,
    ))


def a_remettre(commande):
    """Ce que le livreur doit remettre à la boutique pour cette commande."""
    return commande.net_articles if commande.garde_frais else commande.total


def commande_livree(commande):
    """Appelé quand une commande passe « livrée »."""
    if commande.livree_par_livreur:
        commande.reglee = False      # l'argent est chez le livreur jusqu'au versement
        commande.frais_payes = commande.garde_frais
    else:
        # Remise en main propre : encaissé tout de suite (vente à crédit : seulement la part payée)
        credit = commande.source == 'comptoir' and commande.montant_paye is not None
        montant = commande.montant_paye if credit else commande.total
        commande.reglee = not (credit and (commande.reste_du or 0) > 0.001)
        commande.frais_payes = True
        commande.date_reglement = datetime.utcnow() if commande.reglee else None
        libelle = (f'Vente au comptoir n°{commande.numero}' + (f' ({commande.client_nom})' if commande.client_nom != 'Client comptoir' else '')
                   if commande.source == 'comptoir' else f'Commande n°{commande.numero} remise en boutique ({commande.client_nom})')
        if credit and (commande.reste_du or 0) > 0.001:
            libelle += f' · à crédit, reste {commande.reste_du:,.0f} FCFA'.replace(',', ' ')
        if montant:
            ajouter(commande.boutique_id, 'vente_directe', montant, libelle, commande_id=commande.id)


def commande_plus_livree(commande):
    """Une commande livrée revient en arrière (erreur, annulation) : on corrige la caisse."""
    if commande.source == 'comptoir' and commande.montant_paye is not None:
        # Vente à crédit annulée : on rend ce que le client a payé, la créance disparaît
        if commande.montant_paye:
            ajouter(commande.boutique_id, 'correction', -commande.montant_paye,
                    f'Annulation de la vente n°{commande.numero} : argent à rendre', commande_id=commande.id)
        for p in commande.paiements_creance:
            if p.statut == 'en_attente':
                p.statut, p.motif_refus = 'refuse', 'Vente annulée'
        commande.montant_paye, commande.reste_du = 0, 0
    elif commande.reglee:
        montant = commande.total if not commande.livree_par_livreur else a_remettre(commande)
        ajouter(commande.boutique_id, 'correction', -montant,
                f'Annulation de la livraison n°{commande.numero} : argent à rendre', commande_id=commande.id)
    commande.reglee = False
    commande.date_reglement = None


def enregistrer_versement(livreur, commandes):
    """Le livreur remet l'argent de ces commandes livrées."""
    total = sum(a_remettre(c) for c in commandes)
    if not commandes or total <= 0:
        return 0
    numeros = ', '.join(f'n°{c.numero}' for c in commandes)
    ajouter(livreur.boutique_id, 'versement', total, f'Versement de {livreur.nom} : commandes {numeros}',
            livreur_id=livreur.id)
    for c in commandes:
        c.reglee = True
        c.date_reglement = datetime.utcnow()
    return total


def payer_livreur(livreur, commandes):
    """Le livreur a tout rapporté : la boutique lui paie ses frais."""
    total = sum(c.frais_livraison or 0 for c in commandes)
    if total <= 0:
        return 0
    ajouter(livreur.boutique_id, 'paiement_livreur', -total,
            f'Frais de livraison payés à {livreur.nom} ({len(commandes)} course(s))', livreur_id=livreur.id)
    for c in commandes:
        c.frais_payes = True
    return total
