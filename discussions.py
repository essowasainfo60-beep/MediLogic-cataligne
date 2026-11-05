"""Discussions dans LivraPlus (au lieu de WhatsApp).

- Une discussion par commande : la boutique, le livreur de la commande et le client.
- Une discussion générale par boutique : la boutique et tous ses livreurs.
On peut y envoyer du texte, des photos, des messages vocaux et sa position.
Chaque nouveau message fait sonner les téléphones des autres participants (notifications).
Les participants sont désignés par une clé : « boutique », « client » ou « livreur:<id> ».
"""
from datetime import datetime

from flask import url_for

import notifications
from models import db, Commande, Discussion, LectureDiscussion, Livreur, MediaMessage, Message
from utils import compresser_image

TEXTE_MAX = 2000
AUDIO_MAX_OCTETS = 4 * 1024 * 1024        # ~4 Mo : largement plus de 2 minutes de voix
AUDIO_DUREE_MAX = 180                      # secondes
MIMES_AUDIO = ('audio/webm', 'audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/aac', 'audio/x-m4a', 'audio/wav')

MESSAGES_RAPIDES = {
    'boutique': ['Votre commande est prête ✅', 'Le livreur est en route 🛵', 'Merci pour votre commande 🙏',
                 'Pouvez-vous préciser votre adresse ?'],
    'livreur': ["Je suis en route 🛵", "J'arrive dans 5 minutes", 'Je suis devant chez vous 📍',
                "Je n'arrive pas à vous joindre", 'Livraison effectuée ✅'],
    'client': ["D'accord, merci 🙏", 'Je suis disponible', 'Je ne suis pas encore à la maison',
               'Pouvez-vous me rappeler ?'],
}


# ---------- Accès aux discussions ----------

def discussion_commande(commande):
    d = commande.discussion
    if d is None:
        d = Discussion(boutique_id=commande.boutique_id, commande_id=commande.id)
        db.session.add(d)
        db.session.commit()
    return d


def discussion_privee(livreur):
    """Discussion entre la boutique et CE livreur seulement."""
    d = Discussion.query.filter_by(boutique_id=livreur.boutique_id, commande_id=None, livreur_id=livreur.id).first()
    if d is None:
        d = Discussion(boutique_id=livreur.boutique_id, commande_id=None, livreur_id=livreur.id)
        db.session.add(d)
        db.session.commit()
    return d


def discussion_generale(boutique_id):
    d = Discussion.query.filter_by(boutique_id=boutique_id, commande_id=None, livreur_id=None).first()
    if d is None:
        d = Discussion(boutique_id=boutique_id, commande_id=None)
        db.session.add(d)
        db.session.commit()
    return d


def peut_lire(discussion, qui, livreur=None):
    """Le livreur ne voit que la discussion générale de sa boutique et celles de SES commandes."""
    if qui == 'boutique':
        return True
    if qui == 'client':
        return discussion.commande_id is not None
    if livreur is None or livreur.boutique_id != discussion.boutique_id:
        return False
    if discussion.est_privee:
        return discussion.livreur_id == livreur.id
    return discussion.est_generale or (discussion.commande and discussion.commande.livreur_id == livreur.id)


# ---------- Messages ----------

def _media(boutique_id, donnees, mime):
    m = MediaMessage(boutique_id=boutique_id, mime=mime, donnees=donnees)
    db.session.add(m)
    db.session.flush()
    return m


def poster(discussion, qui, nom, form, fichiers):
    """Crée le message envoyé (texte, photo, audio ou position). Renvoie (message, erreur)."""
    type_ = form.get('type') or 'texte'
    if type_ not in Message.TYPES:
        return None, 'Type de message inconnu'
    msg = Message(discussion_id=discussion.id, auteur=qui, auteur_nom=(nom or '?')[:120], type=type_)
    texte = (form.get('texte') or '').strip()[:TEXTE_MAX]
    if type_ == 'texte':
        if not texte:
            return None, 'Message vide'
        msg.texte = texte
    elif type_ == 'photo':
        fichier = fichiers.get('fichier')
        resultat = compresser_image(fichier) if fichier and fichier.filename else None
        if not resultat:
            return None, 'Photo illisible'
        msg.media = _media(discussion.boutique_id, *resultat)
        msg.texte = texte or None
    elif type_ == 'audio':
        fichier = fichiers.get('fichier')
        if not fichier:
            return None, 'Message vocal manquant'
        donnees = fichier.read(AUDIO_MAX_OCTETS + 1)
        mime = (fichier.mimetype or '').split(';')[0].lower()
        if not donnees or len(donnees) > AUDIO_MAX_OCTETS:
            return None, 'Message vocal trop long'
        if mime not in MIMES_AUDIO:
            return None, 'Format audio non accepté'
        msg.media = _media(discussion.boutique_id, donnees, mime)
        try:
            msg.duree = max(1, min(int(float(form.get('duree') or 0)), AUDIO_DUREE_MAX))
        except ValueError:
            msg.duree = None
    elif type_ == 'position':
        try:
            msg.lat, msg.lng = float(form.get('lat')), float(form.get('lng'))
        except (TypeError, ValueError):
            return None, 'Position illisible'
        if not (-90 <= msg.lat <= 90 and -180 <= msg.lng <= 180):
            return None, 'Position illisible'
    db.session.add(msg)
    discussion.dernier_message_at = datetime.utcnow()
    db.session.flush()
    marquer_lu(discussion, qui, msg.id, commit=False)
    db.session.commit()
    _prevenir(discussion, msg)
    return msg, None


def dernier_message(discussion):
    return Message.query.filter_by(discussion_id=discussion.id).order_by(Message.id.desc()).first()


def apercu(message):
    if message.type == 'photo':
        return '📷 Photo' + (f' : {message.texte}' if message.texte else '')
    if message.type == 'audio':
        return '🎤 Message vocal' + (f' ({message.duree} s)' if message.duree else '')
    if message.type == 'position':
        return '📍 Position partagée'
    return (message.texte or '')[:120]


def en_dict(message, moi, lectures):
    """Message pour l'affichage. `lectures` : {qui: dernier_lu_id} des autres participants."""
    lu_par = [q for q, n in lectures.items() if q != message.auteur and n >= message.id]
    d = {'id': message.id, 'moi': message.auteur == moi, 'auteur': message.auteur, 'nom': message.auteur_nom,
         'role': message.auteur.split(':')[0], 'type': message.type, 'texte': message.texte,
         'heure': message.created_at.strftime('%H:%M'), 'jour': message.created_at.strftime('%d/%m/%Y'),
         'lu': bool(lu_par)}
    if message.media:
        d['media'] = url_for('client.media_message', cle=message.media.cle)
    if message.type == 'audio':
        d['duree'] = message.duree
    if message.type == 'position':
        d.update(lat=message.lat, lng=message.lng,
                 carte=f'https://www.google.com/maps/search/?api=1&query={message.lat},{message.lng}')
    return d


def lectures(discussion):
    return {l.qui: l.dernier_lu_id for l in discussion.lectures}


def messages(discussion, moi, apres_id=0, limite=200):
    q = Message.query.filter(Message.discussion_id == discussion.id, Message.id > apres_id)
    liste = q.order_by(Message.id.desc()).limit(limite).all()[::-1]
    lus = lectures(discussion)
    return [en_dict(m, moi, lus) for m in liste]


def marquer_lu(discussion, qui, jusqu_a_id=None, commit=True):
    if jusqu_a_id is None:
        dernier = dernier_message(discussion)
        jusqu_a_id = dernier.id if dernier else 0
    lecture = LectureDiscussion.query.filter_by(discussion_id=discussion.id, qui=qui).first()
    if lecture is None:
        lecture = LectureDiscussion(discussion_id=discussion.id, qui=qui, dernier_lu_id=0)
        db.session.add(lecture)
    if jusqu_a_id > lecture.dernier_lu_id:
        lecture.dernier_lu_id = jusqu_a_id
        lecture.lu_at = datetime.utcnow()
    if commit:
        db.session.commit()


def non_lus(discussion, qui):
    lecture = LectureDiscussion.query.filter_by(discussion_id=discussion.id, qui=qui).first()
    dernier = lecture.dernier_lu_id if lecture else 0
    return Message.query.filter(Message.discussion_id == discussion.id, Message.id > dernier, Message.auteur != qui).count()


def non_lus_boutique(boutique_id):
    """Nombre total de messages non lus par la boutique (badge du menu)."""
    total = 0
    for d in Discussion.query.filter(Discussion.boutique_id == boutique_id, Discussion.dernier_message_at.isnot(None)).all():
        total += non_lus(d, 'boutique')
    return total


def discussions_livreur(livreur):
    """Discussion générale + discussions des commandes du livreur (en cours ou récentes)."""
    res = [discussion_privee(livreur), discussion_generale(livreur.boutique_id)]
    cmds = (Commande.query.filter_by(livreur_id=livreur.id)
            .filter(Commande.statut.in_(['en_livraison', 'echec', 'livree']))
            .order_by(Commande.date_depart.desc()).limit(30).all())
    for c in cmds:
        if c.discussion is not None or c.statut == 'en_livraison':
            res.append(discussion_commande(c))
    return res


# ---------- Notifications ----------

def _prevenir(discussion, msg):
    """Fait sonner les téléphones des autres participants."""
    texte = f'{msg.auteur_nom} : {apercu(msg)}'
    tag = f'discussion-{discussion.id}'
    commande = discussion.commande
    titre = (f'💬 Commande n°{commande.numero}' if commande else
             '🔒 Message privé' if discussion.est_privee else '💬 Discussion livreurs')
    try:
        if msg.auteur != 'boutique':
            notifications.envoyer_boutique(discussion.boutique_id, titre, texte,
                                           url_for('boutique.discussion', discussion_id=discussion.id), tag=tag)
        if commande:
            if msg.auteur != 'client' and commande.code_suivi:
                notifications.envoyer(commande, titre, texte, url_for('client.discussion_client', code=commande.code_suivi))
            if commande.livreur and msg.auteur != f'livreur:{commande.livreur_id}':
                notifications.envoyer_livreur(commande.livreur, titre, texte,
                                              url_for('client.discussion_livreur', code=commande.livreur.code_acces,
                                                      discussion_id=discussion.id), tag=tag)
        elif discussion.est_privee:
            if msg.auteur != f'livreur:{discussion.livreur_id}':
                notifications.envoyer_livreur(discussion.livreur, titre, texte,
                                              url_for('client.discussion_livreur', code=discussion.livreur.code_acces,
                                                      discussion_id=discussion.id), tag=tag)
        else:
            for livreur in Livreur.query.filter_by(boutique_id=discussion.boutique_id, actif=True).all():
                if msg.auteur != f'livreur:{livreur.id}':
                    notifications.envoyer_livreur(livreur, titre, texte,
                                                  url_for('client.discussion_livreur', code=livreur.code_acces,
                                                          discussion_id=discussion.id), tag=tag)
    except Exception:            # une notification ratée ne doit jamais bloquer l'envoi du message
        pass
