"""Créneaux de livraison proposés au client : « Dès que possible », puis les
tranches encore possibles aujourd'hui et celles de demain et après-demain."""
from datetime import datetime, timedelta

TRANCHES = [('Matin', 'Matin (8h-12h)', 12), ('Après-midi', 'Après-midi (12h-16h)', 16), ('Soir', 'Soir (16h-20h)', 20)]
JOURS = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
DES_QUE_POSSIBLE = 'Dès que possible'


def creneaux_disponibles(maintenant=None):
    maintenant = maintenant or datetime.utcnow()   # heure de Lomé = UTC
    choix = [DES_QUE_POSSIBLE]
    for decalage in range(3):
        jour = maintenant + timedelta(days=decalage)
        nom = "Aujourd'hui" if decalage == 0 else ('Demain' if decalage == 1 else JOURS[jour.weekday()].capitalize())
        for _, libelle, fin in TRANCHES:
            if decalage == 0 and maintenant.hour >= fin - 1:   # tranche (presque) passée
                continue
            choix.append(f"{nom} {jour.strftime('%d/%m')} · {libelle}")
    return choix


AUTRE = 'Autre jour / heure précise…'
DELAI_MIN = timedelta(minutes=30)     # pas d'heure déjà passée ou dans moins de 30 min
HORIZON = timedelta(days=30)


def lire_creneau(form, maintenant=None):
    """Créneau choisi dans le formulaire : un des créneaux proposés, ou une date + heure
    écrites par le client (« Mercredi 12/11 à 15h30 »). Renvoie (créneau, erreur)."""
    maintenant = maintenant or datetime.utcnow()
    choix = (form.get('creneau') or '').strip()
    if choix != AUTRE:
        return (choix if choix in creneaux_disponibles(maintenant) else None), None
    try:
        moment = datetime.strptime(f"{form.get('creneau_date', '')} {form.get('creneau_heure', '')}", '%Y-%m-%d %H:%M')
    except ValueError:
        return None, "Indiquez le jour et l'heure souhaités."
    if moment < maintenant + DELAI_MIN:
        return None, "Choisissez une heure au moins 30 minutes plus tard."
    if moment > maintenant + HORIZON:
        return None, "Choisissez une date dans les 30 prochains jours."
    jour = "Aujourd'hui" if moment.date() == maintenant.date() else (
        'Demain' if moment.date() == (maintenant + timedelta(days=1)).date() else JOURS[moment.weekday()].capitalize())
    return f"{jour} {moment.strftime('%d/%m')} à {moment.strftime('%H')}h{moment.strftime('%M')}", None
