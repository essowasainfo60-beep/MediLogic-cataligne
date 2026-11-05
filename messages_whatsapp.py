"""Messages WhatsApp envoyés aux clients et aux livreurs.
Tous les textes sont ici pour être faciles à relire et à modifier."""
from urllib.parse import quote

from flask import url_for

TRAIT = "━━━━━━━━━━━━━━━━━━"


def fcfa(montant):
    return f"{montant:,.0f}".replace(',', ' ') + " FCFA"


def numero_wa(telephone):
    """Numéro au format WhatsApp (chiffres avec indicatif) : « 90 00 00 00 » → 22890000000.
    Un numéro togolais à 8 chiffres sans indicatif reçoit +228 ; « 00228… » devient « 228… »."""
    numero = ''.join(c for c in (telephone or '') if c.isdigit())
    if numero.startswith('00'):
        numero = numero[2:]
    if len(numero) == 8:
        numero = '228' + numero
    return numero


def lien_whatsapp(telephone, message):
    return f"https://wa.me/{numero_wa(telephone)}?text={quote(message)}"


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


def _retrait(commande):
    """Où et comment récupérer une commande « je passe à la boutique »."""
    b = commande.boutique
    texte = "🛍️ Vous avez choisi de *passer récupérer votre commande à la boutique*.\n\n"
    texte += f"🏁 *Adresse :* {b.adresse or b.nom_boutique}\n"
    if b.lien_itineraire:
        texte += f"🗺️ *Itinéraire :* {b.lien_itineraire}\n"
    if b.whatsapp:
        texte += f"📞 *Boutique :* {b.whatsapp}\n"
    if commande.creneau:
        texte += f"🕒 *Passage prévu :* {commande.creneau}\n"
    return texte + f"\n💵 *À payer sur place : {fcfa(commande.total)}* — présentez le n°{commande.numero}."


def confirmation_client(commande):
    if commande.est_retrait:
        return (f"✅ *COMMANDE N°{commande.numero} CONFIRMÉE*\n{TRAIT}\n"
                f"Bonjour {commande.client_nom},\n\n"
                f"Votre commande est prête : nous vous attendons ! 🙏\n\n"
                f"📦 *Récapitulatif :*\n{_recap(commande)}\n\n"
                f"{_retrait(commande)}\n\n"
                f"Merci pour votre confiance !\n{commande.boutique.nom_boutique}{_suivi(commande)}")
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


def retrait_confirmation_courte(commande):
    """Message posté dans la discussion LivraPlus quand une commande à retirer est confirmée."""
    return (f"✅ Votre commande n°{commande.numero} est prête !\n"
            + _retrait(commande).replace('*', ''))


def nouvelle_commande_boutique(commande, lien_article=None, racine=''):
    """Message « nouvelle commande » envoyé par le client à la boutique (WhatsApp ou messagerie LivraPlus)."""
    m = f"🆕 *NOUVELLE COMMANDE N°{commande.numero}*\n{TRAIT}\n"
    m += f"👤 *Client:* {commande.client_nom}\n📱 *Tél:* {commande.client_telephone}\n"
    if commande.est_retrait:
        m += "🛍️ *Je passe récupérer ma commande à la boutique* (pas de livraison)\n"
        if commande.creneau:
            m += f"🕒 *Passage prévu:* {commande.creneau}\n"
    else:
        m += f"📍 *Adresse:* {commande.client_adresse}\n"
        if commande.zone:
            m += f"🧭 *Zone:* {commande.zone.nom}\n"
        if commande.latitude is not None:
            m += f"🗺️ *Position GPS:* https://maps.google.com/?q={commande.latitude},{commande.longitude}\n"
        if commande.creneau:
            m += f"🕒 *Livraison souhaitée:* {commande.creneau}\n"
    if commande.instructions:
        m += f"\n📝 *Instructions:*\n\"{commande.instructions}\"\n"
    m += f"{TRAIT}\n📦 *ARTICLES COMMANDÉS:*\n\n"
    for item in commande.articles_json:
        m += f"🔹 *{('n°' + str(item['numero']) + ' · ') if item.get('numero') else ''}{item['nom']}*\n"
        m += f"   Quantité: {item['quantite']}\n   Prix unitaire: {fcfa(item['prix'])}\n"
        m += f"   Sous-total: {fcfa(item['prix'] * int(item['quantite']))}\n"
        if item.get('numero') and item.get('photo_num') and lien_article:
            m += f"   🖼️ *Photo choisie : {item['photo_num']}/{item['photos_total']}* → {lien_article(item)}\n"
        elif item.get('photo'):
            photo = item['photo']
            m += f"   🖼️ *Photo:* {racine + photo if photo.startswith('/') else photo}\n"
        m += "\n"
    m += f"{TRAIT}\n"
    if commande.remise:
        m += f"🎁 *Code {commande.code_promo}:* -{fcfa(commande.remise)}\n"
    if commande.frais_livraison:
        m += f"🛵 *Livraison ({commande.zone.nom if commande.zone else ''}):* {fcfa(commande.frais_livraison)}\n"
    m += f"💰 *TOTAL: {fcfa(commande.total)}*" + (" (à payer à la boutique)" if commande.est_retrait else "") + f"\n{TRAIT}"
    return m


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



def arrivee_client(commande):
    """Envoyé par le livreur quand il appuie sur « Je suis arrivé »."""
    nom_livreur = commande.livreur.nom if commande.livreur else 'votre livreur'
    return (f"📍 *VOTRE LIVREUR EST ARRIVÉ*\n{TRAIT}\n"
            f"Bonjour {commande.client_nom},\n\n"
            f"Je suis {nom_livreur}, livreur de {commande.boutique.nom_boutique}.\n"
            f"Je suis arrivé avec votre commande n°{commande.numero} :\n"
            f"🏠 {commande.client_adresse}\n\n"
            f"💰 *À payer : {fcfa(commande.total)}*\n\n"
            f"Je vous attends, merci de sortir 🙏")


def message_statut_defaut(boutique):
    """Message proposé pour le statut WhatsApp de la boutique ({lien} = lien du catalogue)."""
    lignes = [f"🛍️ *{boutique.nom_boutique.strip()}*"]
    if boutique.description:
        lignes.append(boutique.description.strip()[:250])
    nb = sum(1 for a in boutique.articles if not a.archive) if hasattr(boutique, 'articles') else 0
    lignes.append("")
    lignes.append(f"✨ {nb} articles à découvrir en photos" if nb > 1 else "✨ Découvrez nos articles en photos")
    zones = [z for z in boutique.zones if z.active and not z.est_retrait]
    if zones:
        moins_cher = min(z.frais or 0 for z in zones)
        lignes.append("🛵 Livraison à domicile" + (f" dès {fcfa(moins_cher)}" if moins_cher else ""))
    if boutique.zone_retrait:
        lignes.append("🏁 Retrait gratuit à la boutique" + (f" : {boutique.adresse}" if boutique.adresse else ""))
    elif boutique.adresse:
        lignes.append(f"📍 {boutique.adresse}")
    lignes.append("💵 Paiement à la livraison")
    lignes.append("")
    lignes.append("👉 Commandez ici en 1 minute : {lien}")
    return "\n".join(lignes)


def message_statut(boutique, lien):
    """Message du statut : celui de la boutique s'il existe, sinon celui proposé. Le lien y est toujours."""
    texte = (boutique.message_statut or '').strip() or message_statut_defaut(boutique)
    if '{lien}' in texte:
        return texte.replace('{lien}', lien)
    return texte if lien in texte else f"{texte}\n\n👉 {lien}"
