"""Demandes d'articles épuisés : le client laisse un message (« je le veux en 42 »)
et il est prévenu dès que l'article revient.

  - Retour en stock détecté après chaque action de la boutique (entrée de stock, inventaire,
    modification d'article, commande annulée…) : les clients qui ont accepté les notifications
    sont prévenus tout de suite, automatiquement.
  - Les autres (pas de notification sur leur téléphone) sont signalés à la boutique :
    « à prévenir », avec un message WhatsApp tout prêt.
  - La boutique peut aussi faire signe elle-même, à tout moment (notification et/ou WhatsApp)."""
from datetime import datetime

from flask import url_for

import notifications
import stock
import messages_whatsapp as msg
from models import db, DemandeArticle, Article

MAX_PAR_TELEPHONE = 20      # demandes en attente par client et par boutique (évite les abus)


def en_attente(boutique_id):
    return DemandeArticle.query.filter_by(boutique_id=boutique_id, statut=DemandeArticle.ATTENTE)


def nombre_a_traiter(boutique_id):
    """Pastille du menu : demandes jamais vues + articles revenus à signaler par WhatsApp."""
    q = en_attente(boutique_id)
    return q.filter((DemandeArticle.vue.is_(False)) | (DemandeArticle.revenu_at.isnot(None))).count()


def chiffres(telephone):
    """Numéro comparable : « 90 00 00 00 » et « +228 90000000 » sont le même client."""
    return msg.numero_wa(telephone)


def enregistrer(boutique, article, cle, libelle, nom, telephone, message, quantite, abo=None):
    """Crée (ou met à jour) la demande du client. Renvoie (demande, erreur)."""
    nom, telephone, message = (nom or '').strip()[:100], (telephone or '').strip()[:30], (message or '').strip()[:500]
    if not nom:
        return None, 'Indiquez votre nom'
    if len(chiffres(telephone)) < 8:
        return None, 'Indiquez un numéro de téléphone valide (8 chiffres au moins)'
    quantite = max(1, min(int(quantite or 1), 99))
    attente = en_attente(boutique.id)
    demande = next((d for d in attente.filter_by(article_id=article.id, variante=cle).all()
                    if chiffres(d.telephone) == chiffres(telephone)), None)
    if demande is None:
        if sum(1 for d in attente.all() if chiffres(d.telephone) == chiffres(telephone)) >= MAX_PAR_TELEPHONE:
            return None, 'Vous avez déjà beaucoup de demandes en attente dans cette boutique'
        demande = DemandeArticle(boutique_id=boutique.id, article_id=article.id, variante=cle,
                                 variante_libelle=(libelle or '')[:150] or None)
        db.session.add(demande)
    demande.nom, demande.telephone, demande.quantite = nom, telephone, quantite
    demande.message = message or demande.message
    demande.vue = False
    if abo:
        try:
            ep, p, a = abo['endpoint'], abo['keys']['p256dh'], abo['keys']['auth']
            if str(ep).startswith('https://') and len(ep) <= 1000:
                demande.endpoint, demande.cle_p256dh, demande.cle_auth = ep, p, a
        except (KeyError, TypeError):
            pass
    db.session.commit()
    notifications.envoyer_boutique(
        boutique.id, f'📩 Demande : {demande.designation}',
        f'{nom} le veut ({quantite}) mais il est épuisé.' + (f' « {message[:80]} »' if message else ''),
        url_for('boutique.demandes_clients', _external=True), tag=f'demande-{demande.id}')
    return demande, None


def lien_article(demande):
    return url_for('client.catalogue', code=demande.boutique.lien_public, ref='retour-stock', _external=True) \
        + f'#article-{demande.article.numero}'


def message_whatsapp(demande):
    """Message prêt à envoyer au client (la boutique peut le modifier dans WhatsApp)."""
    b = demande.boutique
    lignes = [f"Bonjour {demande.nom} 👋",
              f"C'est {b.nom_boutique}. Bonne nouvelle : *{demande.designation}* est de nouveau disponible !",
              f"Vous nous l'aviez demandé{f' ({demande.quantite})' if demande.quantite > 1 else ''}"
              + (f" : « {demande.message} »" if demande.message else '') + '.',
              '', '👉 Commandez ici avant qu\'il ne reparte :', lien_article(demande)]
    return '\n'.join(lignes)


def lien_whatsapp(demande):
    return msg.lien_whatsapp(demande.telephone, message_whatsapp(demande))


def disponible(demande, reserves):
    """L'article (ou la variante demandée) est-il de nouveau commandable ?"""
    article = demande.article
    if article is None or article.archive:
        return False
    if article.stock is None:          # stock plus suivi : l'article est en vente
        return True
    cle = demande.variante if demande.variante and article.suit_variantes and demande.variante in dict(article.combinaisons()) else None
    return stock.disponible(article, cle, reserves) > 0


def _notifier(demande):
    """Notification sur le téléphone du client. Renvoie True si elle est partie."""
    if not demande.notifiable:
        return False
    a = demande.article
    photo = next((p for p in (a.photos_urls or []) if p), None)
    image = (url_for('client.accueil', _external=True).rstrip('/') + photo) if photo and photo.startswith('/') else photo
    return notifications.envoyer_abonnes(
        [demande], f'🎉 De retour chez {demande.boutique.nom_boutique}',
        f'{demande.designation} est de nouveau disponible. Touchez pour commander avant qu\'il ne reparte !',
        lien_article(demande), f'retour-{demande.id}', doux=True, image=image, oublier=False) > 0


def prevenir(demande, par):
    """La boutique fait signe au client (ou notification automatique). Renvoie True si la notification est partie."""
    envoye = _notifier(demande)
    demande.statut = DemandeArticle.PREVENU
    demande.prevenu_at = datetime.utcnow()
    demande.prevenu_par = (par or '')[:60]
    demande.vue = True
    db.session.commit()
    return envoye


def verifier(boutique_id):
    """Après une action de la boutique : les articles demandés sont-ils revenus ?
    Renvoie [(désignation, prévenus par notification, à prévenir par WhatsApp)]."""
    demandes = en_attente(boutique_id).filter(DemandeArticle.revenu_at.is_(None)).all()
    if not demandes:
        return []
    reserves = stock.reserves(boutique_id)
    bilan = {}
    for d in demandes:
        if not disponible(d, reserves):
            continue
        cle = d.designation
        notifies, whatsapp = bilan.get(cle, (0, 0))
        if d.notifiable and _notifier(d):
            d.statut, d.prevenu_at, d.prevenu_par = DemandeArticle.PREVENU, datetime.utcnow(), 'notification automatique'
            notifies += 1
        else:
            d.revenu_at = datetime.utcnow()          # la boutique le préviendra (WhatsApp)
            whatsapp += 1
        bilan[cle] = (notifies, whatsapp)
    # Revenu puis de nouveau épuisé avant que la boutique ait prévenu : on remet en attente simple
    for d in en_attente(boutique_id).filter(DemandeArticle.revenu_at.isnot(None)).all():
        if not disponible(d, reserves):
            d.revenu_at = None
    db.session.commit()
    return [(nom, n, w) for nom, (n, w) in bilan.items()]


def resume(bilan):
    """Phrase pour la boutique après un retour en stock."""
    morceaux = []
    for nom, n, w in bilan:
        parts = []
        if n:
            parts.append(f'{n} client{"s" if n > 1 else ""} prévenu{"s" if n > 1 else ""} par notification')
        if w:
            parts.append(f'{w} à prévenir par WhatsApp')
        morceaux.append(f'« {nom} » : ' + ' et '.join(parts))
    return '🔔 Des clients attendaient ces articles, de retour en stock. ' + ' · '.join(morceaux) + '.'
