"""Nouveautés : les clients qui l'ont accepté sont prévenus (notification) quand la
boutique ajoute des articles. Pour ne pas les lasser :
  - les nouveautés d'une même journée partent ensemble, en UNE notification ;
  - au plus une annonce par jour et par boutique (les suivantes partent le lendemain,
    automatiquement à la première ouverture de LivraPlus par la boutique) ;
  - le client peut arrêter à tout moment depuis le catalogue."""
from datetime import datetime

from flask import url_for

import notifications
import messages_whatsapp as msg
from models import db, Article, AbonnementNouveautes

EN_ATTENTE = 'en_attente'
ANNONCEE = 'annoncee'


def abonnes(boutique_id):
    return AbonnementNouveautes.query.filter_by(boutique_id=boutique_id).count()


def en_attente(boutique_id):
    return (Article.query.filter_by(boutique_id=boutique_id, annonce=EN_ATTENTE, archive=False, en_ligne=True)
            .order_by(Article.created_at).all())


def annonce_possible(boutique):
    """Pas plus d'une annonce par jour."""
    return not boutique.derniere_annonce or boutique.derniere_annonce.date() < datetime.utcnow().date()


def texte(boutique, articles):
    """(titre, corps) de la notification."""
    if len(articles) == 1:
        a = articles[0]
        prix = ('dès ' if a.prix_differents else '') + msg.fcfa(a.prix_min)
        return f'🆕 Nouveau chez {boutique.nom_boutique}', f'{a.nom} · {prix}. Touchez pour voir.'
    noms = ', '.join(a.nom for a in articles[:3]) + (f' et {len(articles) - 3} autre(s)' if len(articles) > 3 else '')
    return f'🆕 {len(articles)} nouveautés chez {boutique.nom_boutique}', f'{noms}. Touchez pour voir.'


def message_whatsapp(boutique, articles):
    """Texte prêt à partager (statut WhatsApp, liste de diffusion) pour les clients sans notification."""
    lignes = [f"🆕 *Nouveautés chez {boutique.nom_boutique}* !", '']
    for a in articles[:10]:
        lignes.append(f"• {a.nom} : {('dès ' if a.prix_differents else '')}{msg.fcfa(a.prix_min)}")
    lignes += ['', '👉 Commandez ici, livraison rapide :',
               url_for('client.catalogue', code=boutique.lien_public, _external=True)]
    return '\n'.join(lignes)


def annoncer(boutique):
    """Envoie l'annonce des nouveautés en attente. Renvoie (nombre d'articles, téléphones prévenus)."""
    articles = en_attente(boutique.id)
    if not articles or not annonce_possible(boutique):
        return 0, 0
    titre, corps = texte(boutique, articles)
    if len(articles) == 1:
        url = url_for('client.voir_article', code=boutique.lien_public, numero=articles[0].numero, ref='nouveautes', _external=True)
    else:
        url = url_for('client.catalogue', code=boutique.lien_public, ref='nouveautes', _external=True)
    photo = next((p for a in articles for p in (a.photos_urls or []) if p), None)
    image = (url_for('client.accueil', _external=True).rstrip('/') + photo) if photo and photo.startswith('/') else photo
    envoyes = notifications.envoyer_abonnes(
        AbonnementNouveautes.query.filter_by(boutique_id=boutique.id).all(), titre, corps, url,
        f'nouveautes-{boutique.id}', doux=True, image=image)
    for a in articles:
        a.annonce = ANNONCEE
    boutique.derniere_annonce = datetime.utcnow()
    for abonnement in AbonnementNouveautes.query.filter_by(boutique_id=boutique.id).all():
        abonnement.derniere_notif = boutique.derniere_annonce
    db.session.commit()
    return len(articles), envoyes
