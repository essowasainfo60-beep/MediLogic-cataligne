"""Notifications « push » : le téléphone du client sonne et vibre, même page fermée
(Android ; iPhone si la page est ajoutée à l'écran d'accueil).

Les clés VAPID sont créées automatiquement au premier besoin et gardées dans la base
(table parametres) : rien à régler sur Render. Les variables d'environnement
VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY, si elles existent, sont prioritaires."""
import base64
import json
import logging
import os

from sqlalchemy.exc import IntegrityError

from models import db, AbonnementPush, AbonnementPushBoutique, AbonnementPushLivreur, Parametre

log = logging.getLogger(__name__)
CONTACT = 'mailto:' + os.environ.get('VAPID_CONTACT', 'contact@livraplus.app')


def _b64(octets):
    return base64.urlsafe_b64encode(octets).rstrip(b'=').decode()


def cles_vapid():
    """(clé publique pour le navigateur, clé privée) en base64url."""
    if os.environ.get('VAPID_PUBLIC_KEY') and os.environ.get('VAPID_PRIVATE_KEY'):
        return os.environ['VAPID_PUBLIC_KEY'], os.environ['VAPID_PRIVATE_KEY']
    pub, priv = db.session.get(Parametre, 'vapid_public'), db.session.get(Parametre, 'vapid_private')
    if pub and priv:
        return pub.valeur, priv.valeur
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    cle = ec.generate_private_key(ec.SECP256R1())
    priv_b64 = _b64(cle.private_numbers().private_value.to_bytes(32, 'big'))
    pub_b64 = _b64(cle.public_key().public_bytes(serialization.Encoding.X962,
                                                  serialization.PublicFormat.UncompressedPoint))
    try:
        db.session.add_all([Parametre(cle='vapid_public', valeur=pub_b64), Parametre(cle='vapid_private', valeur=priv_b64)])
        db.session.commit()
    except IntegrityError:                     # créées au même moment par une autre requête
        db.session.rollback()
        return db.session.get(Parametre, 'vapid_public').valeur, db.session.get(Parametre, 'vapid_private').valeur
    return pub_b64, priv_b64


def abonner(commande, donnees):
    """Enregistre le téléphone du client (objet PushSubscription du navigateur)."""
    try:
        endpoint = donnees['endpoint']
        p256dh, auth = donnees['keys']['p256dh'], donnees['keys']['auth']
    except (KeyError, TypeError):
        return False
    if not str(endpoint).startswith('https://') or len(endpoint) > 1000:
        return False
    existant = AbonnementPush.query.filter_by(commande_id=commande.id, endpoint=endpoint).first()
    if existant:
        existant.cle_p256dh, existant.cle_auth = p256dh, auth
    else:
        if len(commande.abonnements_push) >= 5:          # quelques téléphones par commande, pas plus
            db.session.delete(commande.abonnements_push[0])
        db.session.add(AbonnementPush(commande_id=commande.id, endpoint=endpoint, cle_p256dh=p256dh, cle_auth=auth))
    db.session.commit()
    return True


def envoyer(commande, titre, corps, url):
    """Envoie la notification à tous les téléphones abonnés à cette commande (client).
    Renvoie le nombre de téléphones prévenus (0 si personne n'est abonné)."""
    return _envoyer(list(commande.abonnements_push), titre, corps, url, f'commande-{commande.id}')


def abonner_boutique(boutique_id, donnees, qui=None):
    """Téléphone de la boutique (gérant ou équipe) qui veut être prévenu des nouvelles commandes."""
    try:
        endpoint = donnees['endpoint']
        p256dh, auth = donnees['keys']['p256dh'], donnees['keys']['auth']
    except (KeyError, TypeError):
        return False
    if not str(endpoint).startswith('https://') or len(endpoint) > 1000:
        return False
    existant = AbonnementPushBoutique.query.filter_by(endpoint=endpoint).first()
    if existant:
        existant.boutique_id, existant.cle_p256dh, existant.cle_auth, existant.qui = boutique_id, p256dh, auth, qui
    else:
        tous = AbonnementPushBoutique.query.filter_by(boutique_id=boutique_id).order_by(AbonnementPushBoutique.id).all()
        if len(tous) >= 20:
            db.session.delete(tous[0])
        db.session.add(AbonnementPushBoutique(boutique_id=boutique_id, endpoint=endpoint, cle_p256dh=p256dh,
                                              cle_auth=auth, qui=qui))
    db.session.commit()
    return True


def envoyer_boutique(boutique_id, titre, corps, url, tag='boutique'):
    """Prévient tous les téléphones de la boutique (nouvelle commande, échec de livraison…)."""
    abonnements = AbonnementPushBoutique.query.filter_by(boutique_id=boutique_id).all()
    return _envoyer(abonnements, titre, corps, url, tag)


def abonner_livreur(livreur, donnees):
    """Téléphone du livreur : il sonnera pour une nouvelle course ou un nouveau message."""
    try:
        endpoint = donnees['endpoint']
        p256dh, auth = donnees['keys']['p256dh'], donnees['keys']['auth']
    except (KeyError, TypeError):
        return False
    if not str(endpoint).startswith('https://') or len(endpoint) > 1000:
        return False
    existant = AbonnementPushLivreur.query.filter_by(endpoint=endpoint).first()
    if existant:
        existant.livreur_id, existant.cle_p256dh, existant.cle_auth = livreur.id, p256dh, auth
    else:
        tous = AbonnementPushLivreur.query.filter_by(livreur_id=livreur.id).order_by(AbonnementPushLivreur.id).all()
        if len(tous) >= 5:
            db.session.delete(tous[0])
        db.session.add(AbonnementPushLivreur(livreur_id=livreur.id, endpoint=endpoint, cle_p256dh=p256dh, cle_auth=auth))
    db.session.commit()
    return True


def envoyer_livreur(livreur, titre, corps, url, tag='livreur'):
    return _envoyer(list(livreur.abonnements_push), titre, corps, url, tag)


def _envoyer(abonnements, titre, corps, url, tag):
    if not abonnements:
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.warning('pywebpush absent : notification non envoyée')
        return 0
    _, cle_privee = cles_vapid()
    message = json.dumps({'titre': titre, 'corps': corps, 'url': url, 'tag': tag})
    envoyes = 0
    for abonnement in abonnements:
        try:
            webpush(subscription_info={'endpoint': abonnement.endpoint,
                                       'keys': {'p256dh': abonnement.cle_p256dh, 'auth': abonnement.cle_auth}},
                    data=message, vapid_private_key=cle_privee, vapid_claims={'sub': CONTACT},
                    ttl=3600, headers={'Urgency': 'high'}, timeout=8)
            envoyes += 1
        except WebPushException as e:
            statut = getattr(e.response, 'status_code', None)
            if statut in (404, 410):                       # téléphone désabonné : on l'oublie
                db.session.delete(abonnement)
            else:
                log.warning('Notification refusée (%s) : %s', statut, e)
        except Exception as e:                             # réseau, clé invalide… ne bloque jamais la livraison
            log.warning('Notification impossible : %s', e)
    db.session.commit()
    return envoyes
