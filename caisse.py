"""Caisse de la boutique : chaque entrée ou sortie d'argent est un MouvementCaisse
(montant positif = entrée, négatif = sortie) ; le solde est leur somme.

Commande livrée par un livreur (paiement à la livraison) :
  - le livreur encaisse le total chez le client ;
  - l'argent des ARTICLES appartient à la boutique : il entre en caisse quand
    le livreur le remet (« versement ») ;
  - les FRAIS DE LIVRAISON appartiennent au livreur. Selon le réglage de la
    boutique (Boutique.mode_frais) :
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
    if commande.boutique.mode_frais == 'boutique_collecte':
        return commande.total
    return commande.net_articles


def commande_livree(commande):
    """Appelé quand une commande passe « livrée »."""
    if commande.livreur_id:
        commande.reglee = False      # l'argent est chez le livreur jusqu'au versement
        commande.frais_payes = commande.boutique.mode_frais != 'boutique_collecte'
    else:
        commande.reglee = True       # remise en main propre : encaissé tout de suite
        commande.frais_payes = True
        commande.date_reglement = datetime.utcnow()
        ajouter(commande.boutique_id, 'vente_directe', commande.total,
                f'Commande n°{commande.numero} remise en boutique ({commande.client_nom})', commande_id=commande.id)


def commande_plus_livree(commande):
    """Une commande livrée revient en arrière (erreur, annulation) : on corrige la caisse."""
    if commande.reglee:
        montant = commande.total if not commande.livreur_id else a_remettre(commande)
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
    """Mode « la boutique collecte tout » : la boutique paie au livreur ses frais."""
    total = sum(c.frais_livraison or 0 for c in commandes)
    if total <= 0:
        return 0
    ajouter(livreur.boutique_id, 'paiement_livreur', -total,
            f'Frais de livraison payés à {livreur.nom} ({len(commandes)} course(s))', livreur_id=livreur.id)
    for c in commandes:
        c.frais_payes = True
    return total
