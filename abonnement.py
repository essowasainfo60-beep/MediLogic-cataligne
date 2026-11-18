"""Abonnement mensuel des boutiques à LivraPlus.

Règles :
- l'administrateur fixe le prix mensuel de chaque boutique et le premier mois facturé ;
  sans prix (ou 0), la boutique n'a rien à payer ;
- chaque mois se paie entre le 1er et le 8 : jaune du 1er au 3, orange du 4 au 6,
  rouge le 7 et le 8 ; après le 8, l'espace boutique est coupé (tableau de bord seulement)
  jusqu'au paiement. Le catalogue des clients et l'espace des livreurs continuent de marcher ;
- le paiement s'enregistre comme une charge « Abonnement logiciel » (montant imposé),
  avec le moyen de paiement, la date et la référence du dépôt (sauf espèces).
"""
import os
from datetime import date, datetime, timedelta

from models import db, Article, Formule, MouvementCaisse, PaiementAbonnement

CATEGORIE = 'Abonnement logiciel'
JOUR_LIMITE = 8

# ---- Formules d'abonnement (table « formules », modifiables depuis l'espace de L'UNIK) ----
# articles / videos : nombre maximum (None = illimité) ; module : vente au comptoir et outils
# « Ma Boutique » (caisse, tickets, scanner, créances, approvisionnement…) ; essai_jours : formule gratuite
# d'essai (bloquée à la fin de l'essai).
DEFAUTS = [
    dict(code='demarrage', nom='Démarrage', prix=0, articles=100, videos=3, module=False, essai_jours=30, couleur='ciel', icone='fa-seedling', ordre=1),
    dict(code='pro', nom='Pro', prix=10000, articles=100, videos=15, module=True, essai_jours=None, couleur='indigo', icone='fa-star', ordre=2),
    dict(code='premium', nom='Premium', prix=25000, articles=None, videos=None, module=True, essai_jours=None, couleur='or', icone='fa-crown', ordre=3),
]
COULEURS = {   # nom → classes du badge
    'ciel': 'bg-sky-100 text-sky-800 border-sky-300', 'indigo': 'bg-indigo-100 text-indigo-800 border-indigo-300',
    'or': 'bg-amber-100 text-amber-800 border-amber-400', 'vert': 'bg-emerald-100 text-emerald-800 border-emerald-300',
    'rose': 'bg-rose-100 text-rose-800 border-rose-300', 'violet': 'bg-purple-100 text-purple-800 border-purple-300',
    'noir': 'bg-gray-900 text-white border-gray-900',
}
ICONES = {'fa-seedling': 'Pousse', 'fa-star': 'Étoile', 'fa-crown': 'Couronne', 'fa-gem': 'Diamant', 'fa-rocket': 'Fusée',
          'fa-bolt': 'Éclair', 'fa-medal': 'Médaille', 'fa-fire': 'Flamme'}
# Boutique qui gère les abonnements de toutes les boutiques (L'UNIK, la boutique phare) :
# toujours Premium, jamais rien à payer, jamais suspendue.
GESTIONNAIRE_ID = int(os.environ.get('LIVRAPLUS_GESTIONNAIRE_ID') or 4)
FORMULE_PHARE = 'premium'
# Le module « Ma Boutique » n'est ouvert qu'aux formules qui l'incluent (Pro, Premium…).
# Une boutique sans formule (anciennes boutiques, en attendant qu'on leur en donne une) garde tout.
MODULE_BOUTIQUE_RESERVE = True


def _vers_dict(f):
    return {'id': f.id, 'code': f.code, 'nom': f.nom, 'prix': f.prix or 0, 'articles': f.articles, 'videos': f.videos,
            'module': f.module, 'essai_jours': f.essai_jours if (f.essai_jours and not f.prix) else None,
            'couleur': COULEURS.get(f.couleur, COULEURS['indigo']), 'nom_couleur': f.couleur, 'icone': f.icone,
            'visible': f.visible, 'ordre': f.ordre}


def formules(toutes=True):
    """{code: infos} dans l'ordre ; crée les 3 formules de départ la première fois."""
    lignes = Formule.query.order_by(Formule.ordre, Formule.prix).all()
    if not lignes:
        for d in DEFAUTS:
            db.session.add(Formule(**d))
        db.session.commit()
        lignes = Formule.query.order_by(Formule.ordre, Formule.prix).all()
    return {f.code: _vers_dict(f) for f in lignes if toutes or f.visible}


def est_gestionnaire(boutique):
    return boutique is not None and boutique.id == GESTIONNAIRE_ID


def infos_formule(boutique):
    """Infos de la formule de la boutique, ou None (pas encore de formule)."""
    if boutique is None:
        return None
    toutes = formules()
    if est_gestionnaire(boutique):
        return toutes.get(FORMULE_PHARE) or {'code': FORMULE_PHARE, 'nom': 'Premium', 'prix': 0, 'articles': None, 'videos': None,
                                             'module': True, 'essai_jours': None, 'couleur': COULEURS['or'], 'icone': 'fa-crown'}
    return toutes.get(boutique.formule) if boutique.formule else None


def formule(boutique):
    f = infos_formule(boutique)
    return f['code'] if f else None


def module_boutique(boutique):
    """La boutique a-t-elle accès à la vente au comptoir et aux outils « Ma Boutique » ?"""
    if not MODULE_BOUTIQUE_RESERVE or boutique is None:
        return True
    f = infos_formule(boutique)
    return True if f is None else f['module']


def formules_avec_module():
    """Texte : « Pro (10 000 FCFA par mois), Premium… » pour expliquer où est la vente au comptoir."""
    avec = [f for f in formules(toutes=False).values() if f['module']]
    return ', '.join(f"{f['nom']} ({int(f['prix']):,} FCFA par mois)".replace(',', ' ') if f['prix'] else f['nom'] for f in avec) or 'supérieures'


def utilisation(boutique):
    """Articles en vente et vidéos utilisées (comptées dans les limites de la formule)."""
    base = Article.query.filter(Article.boutique_id == boutique.id, Article.archive.is_(False))
    return {'articles': base.count(), 'videos': base.filter(Article.video_url.isnot(None)).count()}


def limite(boutique, quoi):
    f = infos_formule(boutique)
    return f[quoi] if f else None


def peut_ajouter(boutique, quoi, combien=1):
    """(True, None) ou (False, message) : 'articles' ou 'videos'."""
    f = infos_formule(boutique)
    maxi = f[quoi] if f else None
    if maxi is None:
        return True, None
    deja = utilisation(boutique)[quoi]
    if deja + combien <= maxi:
        return True, None
    chose = 'articles en vente' if quoi == 'articles' else 'vidéos'
    return False, (f"Votre formule {f['nom']} permet {maxi} {chose} (vous en avez {deja}). "
                   f"Archivez-en un ou passez à une formule supérieure (page Abonnement).")


def choisir_formule(boutique, code, prix=None, debut=None, essai_fin=None):
    """Donne une formule à une boutique (par la boutique gestionnaire). code '' = aucune formule (gratuit)."""
    f = formules().get(code) if code else None
    if code and not f:
        raise ValueError('Formule inconnue')
    boutique.formule = code or None
    if f and f['essai_jours']:
        boutique.abonnement_prix = None
        boutique.abonnement_debut = None
        boutique.essai_fin = essai_fin or boutique.essai_fin or (date.today() + timedelta(days=f['essai_jours']))
    elif f:
        boutique.abonnement_prix = (prix if prix is not None else f['prix']) or None
        boutique.abonnement_debut = (debut or boutique.abonnement_debut or premier_mois_par_defaut()) if boutique.abonnement_prix else None
        boutique.essai_fin = None
    else:
        boutique.abonnement_prix = None
        boutique.abonnement_debut = None
        boutique.essai_fin = None
    db.session.commit()


def nouveau_code(nom):
    """Code court et unique tiré du nom (« Premium Pro Max » → premium-pro-max)."""
    import re
    import unicodedata
    base = unicodedata.normalize('NFKD', nom).encode('ascii', 'ignore').decode().lower()
    base = re.sub(r'[^a-z0-9]+', '-', base).strip('-')[:16] or 'formule'
    code, n = base, 2
    while Formule.query.filter_by(code=code).first():
        code, n = f'{base}-{n}', n + 1
    return code


def enregistrer_formule(f, donnees, appliquer_aux_boutiques=False):
    """Crée ou modifie une formule. donnees : nom, prix, articles, videos, module, essai_jours, couleur, icone, visible.
    Renvoie (formule, nb de boutiques dont le prix a suivi, None) ou (None, 0, erreur)."""
    from models import Boutique
    nom = (donnees.get('nom') or '').strip()[:40]
    if not nom:
        return None, 0, 'Donnez un nom à la formule'
    def entier(v, mini=1):
        v = (str(v) if v is not None else '').strip().replace(' ', '')
        if not v:
            return None
        n = int(float(v.replace(',', '.')))
        if n < mini:
            raise ValueError
        return n
    try:
        prix = float((str(donnees.get('prix') or '0')).replace(' ', '').replace(',', '.'))
        if prix < 0:
            raise ValueError
        articles, videos = entier(donnees.get('articles')), entier(donnees.get('videos'))
        essai = entier(donnees.get('essai_jours'))
        if essai is not None and essai > 365:
            raise ValueError
    except (TypeError, ValueError):
        return None, 0, 'Prix, limites ou jours d\'essai invalides (des nombres positifs, vide = illimité)'
    autre = Formule.query.filter(db.func.lower(Formule.nom) == nom.lower()).first()
    if autre and autre is not f:
        return None, 0, f'Une formule s\'appelle déjà « {nom} »'
    nouvelle = f is None
    if nouvelle:
        f = Formule(code=nouveau_code(nom), ordre=(db.session.query(db.func.max(Formule.ordre)).scalar() or 0) + 1)
        db.session.add(f)
    ancien_prix = f.prix
    f.nom, f.prix, f.articles, f.videos = nom, prix, articles, videos
    f.module = bool(donnees.get('module'))
    f.essai_jours = essai if not prix else None
    f.couleur = donnees.get('couleur') if donnees.get('couleur') in COULEURS else (f.couleur or 'indigo')
    f.icone = donnees.get('icone') if donnees.get('icone') in ICONES else (f.icone or 'fa-star')
    f.visible = bool(donnees.get('visible', True))
    suivies = 0
    if not nouvelle and appliquer_aux_boutiques and ancien_prix != prix and prix:
        # Boutiques sur cette formule qui payaient le prix normal (pas celles qui ont une remise)
        for b in Boutique.query.filter_by(formule=f.code).all():
            if b.abonnement_prix == ancien_prix and not est_gestionnaire(b):
                b.abonnement_prix = prix
                b.abonnement_debut = b.abonnement_debut or premier_mois_par_defaut()
                suivies += 1
    db.session.commit()
    return f, suivies, None


def nb_boutiques(code):
    from models import Boutique
    return Boutique.query.filter_by(formule=code).count()


MOIS_FR = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
           'septembre', 'octobre', 'novembre', 'décembre']


def cle_mois(d):
    return f'{d.year:04d}-{d.month:02d}'


def mois_suivant(cle):
    annee, mois = map(int, cle.split('-'))
    return f'{annee + (mois == 12):04d}-{mois % 12 + 1:02d}'


def libelle_mois(cle):
    annee, mois = map(int, cle.split('-'))
    return f'{MOIS_FR[mois - 1]} {annee}'


def premier_mois_par_defaut(aujourdhui=None):
    """Quand l'administrateur fixe un prix : ce mois-ci si on est encore dans la période
    de paiement (1er–8), sinon le mois prochain (pas de coupure surprise)."""
    aujourdhui = aujourdhui or date.today()
    cle = cle_mois(aujourdhui)
    return cle if aujourdhui.day <= JOUR_LIMITE else mois_suivant(cle)


def mois_payes(boutique):
    return {p.mois for p in boutique.paiements_abonnement if p.statut == 'valide'}


def etat(boutique, aujourdhui=None):
    """Situation de l'abonnement, pour l'affichage et le blocage.
    niveau : 'gratuit', 'ok', 'jaune', 'orange', 'rouge' ou 'bloque'."""
    aujourdhui = aujourdhui or date.today()
    if est_gestionnaire(boutique):
        return {'niveau': 'gratuit', 'exige': False, 'bloque': False, 'prix': 0, 'mois_a_payer': None}
    infos = infos_formule(boutique)
    if infos and infos['essai_jours']:
        fin = boutique.essai_fin or aujourdhui
        reste = (fin - aujourdhui).days
        if reste < 0:
            return {'niveau': 'bloque', 'exige': False, 'bloque': True, 'prix': 0, 'mois_a_payer': None,
                    'essai_fini': True, 'essai_fin': fin}
        return {'niveau': 'gratuit', 'exige': False, 'bloque': False, 'prix': 0, 'mois_a_payer': None,
                'essai': True, 'essai_fin': fin, 'jours_essai': reste}
    mois = cle_mois(aujourdhui)
    prix = boutique.abonnement_prix or 0
    debut = boutique.abonnement_debut
    if not prix or not debut:
        return {'niveau': 'gratuit', 'exige': False, 'bloque': False, 'prix': 0, 'mois_a_payer': None}
    payes = mois_payes(boutique)
    # Mois que le prochain paiement réglera : le premier mois dû non payé (à partir du mois courant)
    a_payer = max(mois, debut)
    while a_payer in payes:
        a_payer = mois_suivant(a_payer)
    res = {'exige': True, 'prix': prix, 'mois_a_payer': a_payer, 'libelle_mois_a_payer': libelle_mois(a_payer),
           'mois_courant_paye': mois in payes or mois < debut, 'jours_restants': None}
    if res['mois_courant_paye']:
        res.update(niveau='ok', bloque=False)
        return res
    jour = aujourdhui.day
    res['jours_restants'] = max(JOUR_LIMITE - jour, 0)
    if jour > JOUR_LIMITE:
        res.update(niveau='bloque', bloque=True)
    elif jour >= 7:
        res.update(niveau='rouge', bloque=False)
    elif jour >= 4:
        res.update(niveau='orange', bloque=False)
    else:
        res.update(niveau='jaune', bloque=False)
    return res


MODES = PaiementAbonnement.MODES


def enregistrer(boutique, mode, reference, date_paiement, par=None):
    """Enregistre le paiement du mois dû. Renvoie (paiement, erreur)."""
    situation = etat(boutique)
    if not situation['exige']:
        return None, "Votre boutique n'a pas d'abonnement à payer."
    if mode not in MODES:
        return None, 'Choisissez le moyen de paiement.'
    reference = (reference or '').strip().upper()[:80]
    if mode != 'especes':
        if len(reference) < 4:
            return None, f'Indiquez la référence du dépôt {MODES[mode]} (au moins 4 caractères).'
        deja = (PaiementAbonnement.query.filter_by(mode=mode, reference=reference, statut='valide').first())
        if deja:
            return None, 'Cette référence de dépôt a déjà été utilisée pour un autre paiement.'
    else:
        reference = None
    if not date_paiement:
        return None, 'Indiquez la date du dépôt.'
    if date_paiement > date.today():
        return None, 'La date du dépôt ne peut pas être dans le futur.'
    if (date.today() - date_paiement).days > 45:
        return None, 'Cette date de dépôt est trop ancienne (plus de 45 jours).'
    mois = situation['mois_a_payer']
    if mois > mois_suivant(cle_mois(date.today())):
        return None, f"L'abonnement est déjà payé jusqu'à {libelle_mois(mois)} exclu. Merci !"

    libelle = f"Abonnement LivraPlus {libelle_mois(mois)} · {MODES[mode]}" + (f" réf. {reference}" if reference else '')
    mouvement = MouvementCaisse(boutique_id=boutique.id, type='charge', categorie=CATEGORIE, libelle=libelle[:200],
                                montant=-situation['prix'], par=par,
                                date=datetime.combine(date_paiement, datetime.utcnow().time()))
    db.session.add(mouvement)
    db.session.flush()
    paiement = PaiementAbonnement(boutique_id=boutique.id, mois=mois, montant=situation['prix'], mode=mode,
                                  reference=reference, date_paiement=date_paiement, par=par, mouvement_id=mouvement.id)
    db.session.add(paiement)
    db.session.commit()
    return paiement, None


def annuler(paiement):
    """Par l'administrateur (référence fausse, dépôt non reçu…) : le mois redevient dû."""
    if paiement.statut != 'valide':
        return
    paiement.statut = 'annule'
    if paiement.mouvement_id:
        mouvement = db.session.get(MouvementCaisse, paiement.mouvement_id)
        if mouvement:
            db.session.delete(mouvement)
        paiement.mouvement_id = None
    db.session.commit()
