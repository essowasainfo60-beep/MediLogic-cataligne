"""Zones de livraison proposées pour Lomé, comme point de départ : la boutique
coche celles qu'elle dessert, ajuste quartiers et prix, puis les crée.
Les prix supposent une boutique au centre-ville ; ils sont tous modifiables."""

ZONES_LOME = [
    {'nom': 'Retrait en boutique', 'frais': 0,
     'quartiers': 'Le client vient récupérer sa commande'},
    {'nom': 'Centre-ville', 'frais': 500,
     'quartiers': 'Grand marché, Assigamé, Adawlato, Kokétimé, Nyékonakpoè, Kodjoviakopé, Hanoukopé, Amoutivé'},
    {'nom': 'Bè et environs', 'frais': 1000,
     'quartiers': 'Bè Kpota, Bè Klikamé, Ablogamé, Akodessewa, Hédzranawoé, Kanyikopé'},
    {'nom': 'Tokoin', 'frais': 1000,
     'quartiers': 'Tokoin Hôpital, Tokoin Wuiti, Tokoin Gbonvié, Tokoin Forever, Doumassessé, Casablanca'},
    {'nom': 'Nord-Est', 'frais': 1500,
     'quartiers': 'Kégué, Adakpamé, Totsi, Atikoumé, Agbalépédogan, Nukafu'},
    {'nom': 'Ouest', 'frais': 1500,
     'quartiers': 'Adidogomé, Avédji, Djidjolé, Wessomé, Aflao Gakli'},
    {'nom': 'Agoè et Nord', 'frais': 2000,
     'quartiers': 'Agoè, Adidoadin, Légbassito, Togblékopé, Zanguéra, Sagbado'},
    {'nom': 'Est et zone portuaire', 'frais': 2000,
     'quartiers': 'Baguida, Avépozo, Agbavi, Kpogan, Zone portuaire'},
    {'nom': 'Hors Lomé', 'frais': 3000,
     'quartiers': 'Tsévié, Aného, Kpalimé… (à confirmer avec le client)'},
]
