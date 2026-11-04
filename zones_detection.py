"""Reconnaît la zone de livraison à partir de l'adresse écrite par le client.

Chaque zone liste ses quartiers (« Agoè, Adidoadin, Légbassito… »). Si l'adresse
contient l'un d'eux (« AGOE TELESSOU » contient « Agoè »), on en déduit la zone,
sans tenir compte des accents ni des majuscules. Le quartier le plus précis
l'emporte (« Bè Kpota » avant « Bè ») ; si deux zones différentes correspondent
avec la même précision, on ne décide pas (None).

La même logique existe côté navigateur (templates : `detecterZone`) pour montrer
le bon prix au client avant qu'il valide.
"""
import re
import unicodedata


def normaliser(texte):
    texte = unicodedata.normalize('NFD', texte or '')
    texte = ''.join(c for c in texte if unicodedata.category(c) != 'Mn').lower()
    return ' '.join(re.findall(r'[a-z0-9]+', texte))


def quartiers_de(zone):
    """Quartiers d'une zone, normalisés (le nom de la zone compte aussi)."""
    morceaux = re.split(r'[,;/\n]', zone.quartiers or '')
    candidats = [m for m in morceaux if '…' not in m and '(' not in m] + [zone.nom]
    vus = []
    for m in candidats:
        n = normaliser(m)
        if len(n) >= 2 and n not in vus and n not in ('zone', 'centre ville', 'retrait en boutique', 'hors lome'):
            vus.append(n)
    return vus


def zone_pour_adresse(adresse, zones):
    """(zone, quartier reconnu) pour cette adresse, ou (None, None)."""
    texte = f' {normaliser(adresse)} '
    if not texte.strip():
        return None, None
    meilleur, quartier, longueur, ambigu = None, None, 0, False
    for zone in zones:
        for q in quartiers_de(zone):
            if f' {q} ' in texte:
                if len(q) > longueur:
                    meilleur, quartier, longueur, ambigu = zone, q, len(q), False
                elif len(q) == longueur and zone is not meilleur:
                    ambigu = True
    if ambigu:
        return None, None
    return meilleur, quartier


def index_quartiers(zones):
    """Pour le navigateur : [{zone_id, quartier normalisé}], du plus précis au moins précis."""
    lignes = [{'zone': z.id, 'q': q} for z in zones for q in quartiers_de(z)]
    return sorted(lignes, key=lambda l: -len(l['q']))
