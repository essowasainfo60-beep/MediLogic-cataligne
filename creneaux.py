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
