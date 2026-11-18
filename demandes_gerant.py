"""Demandes du vendeur au gérant (comme dans Ma Boutik) : rien ne sort de la caisse et aucune
vente n'est annulée sans l'accord du gérant (ou du caissier).

  - 'charge'           : le vendeur a besoin d'argent de la caisse (transport, achat, petite dépense…) ;
  - 'annulation_vente' : le vendeur s'est trompé sur une vente au comptoir.
Validée : la charge sort de la caisse / la vente est annulée (stock remis, argent rendu).
Refusée : rien ne change, le vendeur voit le motif."""
from datetime import datetime

import caisse
import stock
import messages_whatsapp as msg
from models import db, DemandeGerant, Commande, MouvementCaisse

TYPES = {'charge': 'Sortie de caisse (charge)', 'annulation_vente': 'Annulation de vente'}


def en_attente(boutique_id):
    return (DemandeGerant.query.filter_by(boutique_id=boutique_id, statut='en_attente')
            .order_by(DemandeGerant.date).all())


def demander_charge(boutique_id, montant, categorie, motif, par):
    try:
        montant = round(float(montant), 2)
    except (TypeError, ValueError):
        return None, 'Montant invalide'
    if montant <= 0:
        return None, 'Montant invalide'
    motif = (motif or '').strip()[:200]
    if not motif:
        return None, 'Expliquez à quoi sert cet argent'
    d = DemandeGerant(boutique_id=boutique_id, type='charge', montant=montant,
                      categorie=categorie if categorie in MouvementCaisse.CATEGORIES else 'Divers',
                      motif=motif, demandeur=(par or '')[:120])
    db.session.add(d)
    db.session.commit()
    return d, None


def demander_annulation(commande, motif, par):
    if commande.source != 'comptoir' or commande.statut != 'livree':
        return None, 'Seule une vente au comptoir en cours peut être annulée'
    if DemandeGerant.query.filter_by(commande_id=commande.id, type='annulation_vente', statut='en_attente').first():
        return None, 'Une demande d\'annulation attend déjà le gérant pour cette vente'
    motif = (motif or '').strip()[:200]
    if not motif:
        return None, 'Indiquez pourquoi la vente doit être annulée'
    d = DemandeGerant(boutique_id=commande.boutique_id, type='annulation_vente', commande_id=commande.id,
                      montant=commande.total, motif=motif, demandeur=(par or '')[:120])
    db.session.add(d)
    db.session.commit()
    return d, None


def valider(d, par):
    if d.statut != 'en_attente':
        return 'Cette demande a déjà été traitée'
    if d.type == 'charge':
        caisse.ajouter(d.boutique_id, 'charge', -d.montant, f'{d.motif} (demandé par {d.demandeur})', categorie=d.categorie)
    elif d.type == 'annulation_vente':
        c = d.commande
        if not c or c.statut != 'livree':
            return 'La vente n\'est plus annulable (déjà annulée ou retournée)'
        refus = stock.refus_transition(c, 'annulee')
        if refus:
            return refus
        stock.changer_statut(c, 'annulee')
        c.instructions = ((c.instructions or '') + '\n' + f'Annulée (demande de {d.demandeur}, validée par {par}) : {d.motif}').strip()
    d.statut, d.traite_par, d.date_traitement = 'validee', (par or '')[:120], datetime.utcnow()
    db.session.commit()
    return None


def refuser(d, par, motif):
    if d.statut != 'en_attente':
        return 'Cette demande a déjà été traitée'
    d.statut, d.traite_par, d.date_traitement = 'refusee', (par or '')[:120], datetime.utcnow()
    d.motif_refus = (motif or '').strip()[:200] or None
    db.session.commit()
    return None


def resume(d):
    if d.type == 'charge':
        return f'{d.categorie} : {msg.fcfa(d.montant)} — {d.motif}'
    return f'Vente n°{d.commande.numero if d.commande else "?"} ({msg.fcfa(d.montant)}) — {d.motif}'
