"""Suivi GPS des livreurs pendant leurs courses.

Le téléphone du livreur envoie sa position (page « Mes livraisons » ouverte) tant qu'il a
au moins une commande « en livraison ». Le client voit le livreur sur la carte avec la
distance et l'heure d'arrivée estimées ; la boutique voit tous les livreurs en route et le
trajet de chaque course. En dehors des courses, rien n'est enregistré.
"""
import math
from datetime import datetime, timedelta

from models import db, Commande, PositionLivreur

INTERVALLE_MIN_S = 8            # pas plus d'une position toutes les 8 s par livreur
PRECISION_MAX_M = 1000          # au-delà, la position n'est pas utilisable
VITESSE_MOTO_KMH = 22           # vitesse moyenne d'une moto en ville (Lomé), pour l'heure d'arrivée
DETOUR = 1.35                   # la route est plus longue que la ligne droite
CONSERVATION_JOURS = 30


def distance_km(lat1, lng1, lat2, lng2):
    """Distance à vol d'oiseau (formule de haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def courses_en_cours(livreur):
    return Commande.query.filter_by(livreur_id=livreur.id, statut='en_livraison').all()


def enregistrer(livreur, donnees):
    """Position envoyée par le téléphone du livreur. Renvoie (actif, message)."""
    if not courses_en_cours(livreur):
        return False, 'Aucune course en cours : suivi arrêté.'
    try:
        lat, lng = float(donnees.get('lat')), float(donnees.get('lng'))
        precision = float(donnees.get('precision') or 0)
    except (TypeError, ValueError):
        return True, 'Position illisible'
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or precision > PRECISION_MAX_M:
        return True, 'Position trop imprécise'
    maintenant = datetime.utcnow()
    if livreur.position_at and (maintenant - livreur.position_at).total_seconds() < INTERVALLE_MIN_S:
        return True, 'ok'
    vitesse = donnees.get('vitesse')
    try:
        vitesse = round(float(vitesse) * 3.6, 1) if vitesse not in (None, '') else None   # m/s → km/h
    except (TypeError, ValueError):
        vitesse = None
    db.session.add(PositionLivreur(livreur_id=livreur.id, lat=lat, lng=lng, precision=round(precision),
                                   vitesse=vitesse, created_at=maintenant))
    livreur.position_lat, livreur.position_lng, livreur.position_at = lat, lng, maintenant
    # Ménage : on ne garde que les 30 derniers jours
    PositionLivreur.query.filter(PositionLivreur.livreur_id == livreur.id,
                                 PositionLivreur.created_at < maintenant - timedelta(days=CONSERVATION_JOURS)
                                 ).delete(synchronize_session=False)
    db.session.commit()
    return True, 'ok'


def situation(commande):
    """Pour la page de suivi du client et la boutique : où est le livreur, à quelle distance."""
    livreur = commande.livreur
    if commande.statut != 'en_livraison' or not livreur or not livreur.position_at \
            or (commande.date_depart and livreur.position_at < commande.date_depart):
        return None
    il_y_a = int((datetime.utcnow() - livreur.position_at).total_seconds())
    res = {'lat': livreur.position_lat, 'lng': livreur.position_lng, 'heure': livreur.position_at.strftime('%H:%M'),
           'il_y_a_s': il_y_a, 'nom': livreur.nom, 'destination': None, 'distance_km': None, 'arrivee_min': None}
    if commande.latitude is not None and commande.longitude is not None:
        d = distance_km(livreur.position_lat, livreur.position_lng, commande.latitude, commande.longitude) * DETOUR
        res.update(destination={'lat': commande.latitude, 'lng': commande.longitude},
                   distance_km=round(d, 1), arrivee_min=max(1, round(d / VITESSE_MOTO_KMH * 60)))
    return res


def trajet(commande, max_points=400):
    """Positions du livreur pendant cette course (de la remise au livreur à la fin)."""
    if not commande.livreur_id or not commande.date_depart:
        return []
    fin = (commande.date_livraison or commande.date_echec) if commande.statut != 'en_livraison' else None
    if fin and fin < commande.date_depart:
        fin = None
    q = PositionLivreur.query.filter(PositionLivreur.livreur_id == commande.livreur_id,
                                     PositionLivreur.created_at >= commande.date_depart)
    if fin:
        q = q.filter(PositionLivreur.created_at <= fin + timedelta(minutes=2))
    points = q.order_by(PositionLivreur.created_at).all()
    if len(points) > max_points:                       # on allège les très longues courses
        pas = len(points) / max_points
        points = [points[int(i * pas)] for i in range(max_points)] + [points[-1]]
    return [{'lat': p.lat, 'lng': p.lng, 'heure': p.created_at.strftime('%H:%M'), 'vitesse': p.vitesse} for p in points]
