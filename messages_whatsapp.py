"""Messages WhatsApp envoyés aux clients et aux livreurs.
Tous les textes sont ici pour être faciles à relire et à modifier."""
from urllib.parse import quote

from flask import url_for

TRAIT = "━━━━━━━━━━━━━━━━━━"


def fcfa(montant):
    return f"{montant:,.0f}".replace(',', ' ') + " FCFA"


def lien_whatsapp(telephone, message):
    numero = ''.join(c for c in (telephone or '') if c.isdigit())
    return f"https://wa.me/{numero}?text={quote(message)}"


def lien_suivi(commande):
    return url_for('client.suivi', code=commande.code_suivi, _external=True) if commande.code_suivi else ''


def _suivi(commande):
    lien = lien_suivi(commande)
    return f"\n\n📍 Suivre ma commande : {lien}" if lien else ""


def _recap(commande):
    lignes = [f"   • {a['nom']} x{a['quantite']} = {fcfa(a['prix'] * a['quantite'])}" for a in commande.articles_json]
    texte = "\n".join(lignes)
    if commande.remise:
        texte += f"\n   🎁 Code {commande.code_promo} = -{fcfa(commande.remise)}"
    if commande.frais_livraison:
        texte += f"\n   🛵 Livraison{' (' + commande.zone.nom + ')' if commande.zone else ''} = {fcfa(commande.frais_livraison)}"
    return texte + f"\n\n💰 *TOTAL : {fcfa(commande.total)}*"


def confirmation_client(commande):
    return (f"✅ *COMMANDE CONFIRMÉE N°{commande.numero}*\n{TRAIT}\n"
            f"Bonjour {commande.client_nom},\n\n"
            f"Nous avons bien reçu votre commande.\n\n"
            f"📦 *Récapitulatif :*\n{_recap(commande)}\n\n"
            f"📞 Votre commande est en cours de préparation.\n"
            f"Merci pour votre confiance !\n{commande.boutique.nom_boutique}{_suivi(commande)}")


def livreur_en_route_client(commande):
    livreur = commande.livreur
    return (f"🛵 *VOTRE COMMANDE N°{commande.numero} EST EN ROUTE*\n{TRAIT}\n"
            f"Bonjour {commande.client_nom},\n\n"
            f"Nous avons bien reçu votre commande et elle vient de partir en livraison.\n\n"
            f"👤 *Livreur :* {livreur.nom}\n"
            f"📱 *Son numéro :* {livreur.telephone}\n\n"
            f"📦 *Récapitulatif :*\n{_recap(commande)}\n\n"
            f"💵 Le paiement se fait à la livraison.\n\n"
            f"Merci beaucoup pour votre confiance ! 🙏\n{commande.boutique.nom_boutique}{_suivi(commande)}")


def espace_livreur(livreur, lien_espace):
    return (f"🛵 *ESPACE LIVREUR - {livreur.boutique.nom_boutique}*\n{TRAIT}\n"
            f"Bonjour {livreur.nom},\n\n"
            f"Voici votre espace personnel : vous y verrez toutes les livraisons qui vous sont confiées "
            f"(client, adresse, carte, montant), et vous marquerez chaque commande « Livrée » une fois remise.\n\n"
            f"👉 {lien_espace}\n\n"
            f"Astuce : ouvrez le lien puis « Ajouter à l'écran d'accueil » pour l'installer comme une application.\n"
            f"⚠️ Ce lien est personnel, ne le partagez pas.")


def course_livreur(commande, lien_livraison):
    texte = (f"📦 *NOUVELLE LIVRAISON - COMMANDE N°{commande.numero}*\n{TRAIT}\n"
             f"Boutique : {commande.boutique.nom_boutique}\n\n"
             f"👤 *Client :* {commande.client_nom}\n"
             f"📱 *Tél :* {commande.client_telephone}\n"
             f"📍 *Adresse :* {commande.client_adresse}\n"
             + (f"🧭 *Zone :* {commande.zone.nom}\n" if commande.zone else "") +
             f"🗺️ *Itinéraire :* {commande.lien_carte}\n"
             + (f"🕒 *Livraison souhaitée :* {commande.creneau}\n" if commande.creneau else ""))
    if commande.instructions:
        texte += f"📝 *Instructions :* {commande.instructions}\n"
    texte += (f"{TRAIT}\n{_recap(commande)}\n"
              f"💵 *À encaisser à la livraison : {fcfa(commande.total)}*\n{TRAIT}\n"
              f"✅ Une fois livré, validez ici :\n{lien_livraison}")
    return texte


def livree_client(commande):
    return (f"🎉 *COMMANDE N°{commande.numero} LIVRÉE*\n{TRAIT}\n"
            f"Bonjour {commande.client_nom},\n\n"
            f"Votre commande vous a bien été livrée.\n"
            f"Merci pour votre achat et à très bientôt ! 🙏\n\n"
            f"{commande.boutique.nom_boutique}")


def echec_client(commande):
    """La boutique reprend contact après une livraison ratée."""
    return (f"Bonjour {commande.client_nom},\n\n"
            f"Notre livreur n'a pas pu vous remettre votre commande n°{commande.numero}"
            + (f" ({commande.motif_echec.lower()})" if commande.motif_echec else "") + ".\n"
            f"Quand êtes-vous disponible pour la recevoir ? Répondez-nous ici et nous la relançons.\n\n"
            f"{commande.boutique.nom_boutique}{_suivi(commande)}")

