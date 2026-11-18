"""Espace « Mixx & Flooz » : le kiosque mobile money de la boutique.

Pour chaque opérateur (Mixx by Yas, Moov Money / Flooz) la boutique a un SOLDE électronique (sa puce),
et le kiosque a des ESPÈCES. Chaque opération change l'un et/ou l'autre :

  dépôt      le client donne montant + frais en espèces, on envoie le montant sur son numéro
             → espèces + (montant + frais), solde − montant
  retrait    le client envoie montant + frais sur notre numéro, on lui donne le montant en espèces
             → solde + (montant + frais), espèces − montant
  transfert  le client donne montant + frais en espèces, on envoie le montant à la personne de son choix
             → espèces + (montant + frais), solde − montant
  recharge   le grossiste charge notre compte → solde + montant (espèces − montant si payé avec la caisse)
  ajustement le point de la journée corrige l'écart entre le calcul et la réalité

Les frais viennent d'une grille par tranches (modifiable par la boutique, applicable ou non, modifiable
à chaque opération) : c'est ce que gagne la boutique. Chaque opération a une référence LivraPlus
automatique (MX-0001, FL-0001…) et la référence du SMS de l'opérateur (obligatoire, jamais deux fois).

Les espèces ont leur propre caisse (« séparée », par défaut), ou passent dans la caisse de la boutique
(« avec la boutique » : chaque opération y crée un mouvement « Mixx / Flooz »)."""
from datetime import datetime, timedelta

import caisse
from models import db, OperationMomo

OPERATEURS = {'mixx': 'Mixx by Yas', 'flooz': 'Moov Money (Flooz)'}
COURTS = {'mixx': 'Mixx', 'flooz': 'Flooz'}
TYPES = {'depot': 'Dépôt', 'retrait': 'Retrait', 'transfert': 'Transfert', 'recharge': 'Recharge du compte',
         'ajustement': 'Ajustement (point)'}
CLIENT = ('depot', 'retrait', 'transfert')            # opérations avec un client (frais, SMS obligatoire)
SEUIL_DEFAUT = 20000
# Grilles de départ : tarifs de retrait publiés (Mixx by Yas, février 2025 ; Moov Africa Togo).
# Au-dessus de 100 000 F Moov donne des fourchettes : valeur moyenne retenue, à vérifier par la boutique.
GRILLES_DEFAUT = {
    'mixx': [[500, 50], [5000, 100], [20000, 300], [50000, 600], [100000, 1000], [200000, 3100], [300000, 3700],
             [500000, 4200], [850000, 4400], [1000000, 5100]],
    'flooz': [[500, 50], [1000, 75], [5000, 100], [15000, 280], [20000, 320], [50000, 600], [100000, 1000],
              [200000, 3260], [300000, 3960], [500000, 4290], [850000, 4475], [1000000, 4990]],
}
TAILLE_PHOTO = 1600


def grilles(boutique):
    g = boutique.momo_grilles or {}
    return {op: (g.get(op) if isinstance(g.get(op), list) and g.get(op) else GRILLES_DEFAUT[op]) for op in OPERATEURS}


def frais_grille(boutique, operateur, montant):
    if not montant or montant <= 0:
        return 0
    g = grilles(boutique)[operateur]
    for maxi, frais in g:
        if montant <= maxi:
            return frais
    return g[-1][1]


def reglages(boutique):
    r = boutique.momo_reglages or {}
    return {'marchand': {op: bool((r.get('marchand') or {}).get(op)) for op in OPERATEURS},
            'annulation_max': {op: (r.get('annulation_max') or {}).get(op) for op in OPERATEURS}}


def a_code_marchand(boutique, operateur):
    return reglages(boutique)['marchand'][operateur]


def peut_annuler_transfert(boutique, op):
    """Annuler un transfert chez l'opérateur n'est possible qu'en dessous d'un montant (fixé par l'opérateur,
    noté dans les réglages). Renvoie (True, None) ou (False, message)."""
    maxi = reglages(boutique)['annulation_max'][op.operateur]
    if maxi and op.montant > maxi:
        return False, (f"Au-dessus de {maxi:,.0f} F, {COURTS[op.operateur]} ne permet plus d'annuler un transfert : "
                       f"ce transfert ne peut pas être annulé.").replace(',', ' ')
    return True, None


def seuil(boutique):
    return boutique.momo_seuil if boutique.momo_seuil is not None else SEUIL_DEFAUT


def caisse_separee(boutique):
    return (boutique.momo_caisse or 'separee') != 'boutique'


def _valides(boutique_id):
    return OperationMomo.query.filter(OperationMomo.boutique_id == boutique_id, OperationMomo.annulee.is_(False))


def soldes(boutique_id):
    """{'mixx': solde, 'flooz': solde, 'especes': espèces du kiosque}."""
    res = {'mixx': 0.0, 'flooz': 0.0, 'especes': 0.0}
    for op, ds, de in (db.session.query(OperationMomo.operateur, db.func.sum(OperationMomo.delta_solde),
                                        db.func.sum(OperationMomo.delta_especes))
                       .filter(OperationMomo.boutique_id == boutique_id, OperationMomo.annulee.is_(False))
                       .group_by(OperationMomo.operateur).all()):
        res[op] = float(ds or 0)
        res['especes'] += float(de or 0)
    return res


def prochain_numero(boutique_id, operateur):
    n = (db.session.query(db.func.max(OperationMomo.numero))
         .filter_by(boutique_id=boutique_id, operateur=operateur).scalar()) or 0
    return n + 1


def sms_deja_utilise(boutique_id, operateur, sms_ref):
    return _valides(boutique_id).filter(OperationMomo.operateur == operateur,
                                        db.func.upper(OperationMomo.sms_ref) == sms_ref.upper()).first()


def _nombre(v):
    try:
        return float(str(v).replace(' ', '').replace(',', '.'))
    except (TypeError, ValueError):
        return None


def enregistrer(boutique, operateur, type_, montant, telephone='', sms_ref='', appliquer_frais=True, frais=None,
                client_telephone='', paye_caisse=False, photo=None, par=None, note=None, marchand=False):
    """Enregistre une opération. Renvoie (operation, None) ou (None, message d'erreur)."""
    if operateur not in OPERATEURS or type_ not in TYPES or type_ == 'ajustement':
        return None, 'Opération inconnue'
    m = _nombre(montant)
    if not m or m <= 0 or m > 5000000:
        return None, 'Indiquez un montant valide'
    m = round(m)
    sms_ref = (sms_ref or '').strip().upper()[:80]
    if not sms_ref:
        return None, f"La référence du SMS {COURTS[operateur]} est obligatoire : l'opération ne peut pas être enregistrée sans elle."
    if sms_deja_utilise(boutique.id, operateur, sms_ref):
        return None, f'La référence SMS « {sms_ref} » a déjà été enregistrée pour une autre opération.'
    telephone = ''.join(c for c in (telephone or '') if c.isdigit() or c == '+')[:30]
    if type_ in CLIENT and len([c for c in telephone if c.isdigit()]) < 8:
        return None, 'Indiquez le numéro du ' + ('destinataire' if type_ == 'transfert' else 'client') + ' (8 chiffres au moins)'
    fg = frais_grille(boutique, operateur, m) if type_ in CLIENT else 0
    marchand = bool(marchand) and type_ in CLIENT and a_code_marchand(boutique, operateur)
    if type_ not in CLIENT or not appliquer_frais or marchand:
        f = 0
    elif frais in (None, ''):
        f = fg
    else:
        f = _nombre(frais)
        if f is None or f < 0 or f > m:
            return None, 'Frais invalides'
        f = round(f)
    s = soldes(boutique.id)
    if type_ in ('depot', 'transfert'):
        if m > s[operateur]:
            return None, f"Solde {COURTS[operateur]} insuffisant ({s[operateur]:,.0f} F). Rechargez le compte d'abord.".replace(',', ' ')
        ds, de = -m, m + f
    elif type_ == 'retrait':
        if m > s['especes']:
            return None, f"Pas assez d'espèces dans le kiosque ({s['especes']:,.0f} F).".replace(',', ' ')
        ds, de = m + f, -m
    else:   # recharge
        ds, de = m, (-m if paye_caisse else 0)
    op = OperationMomo(boutique_id=boutique.id, operateur=operateur, type=type_, montant=m, frais=f, frais_grille=fg,
                       delta_solde=ds, delta_especes=de, telephone=telephone or None,
                       client_telephone=''.join(c for c in (client_telephone or '') if c.isdigit() or c == '+')[:30] or None,
                       sms_ref=sms_ref, note=(note or '').strip()[:200] or None, par=(par or '')[:120] or None, marchand=marchand,
                       photo=photo[0] if photo else None, photo_mime=photo[1] if photo else None)
    for _ in range(3):      # numéro suivant (deux vendeurs en même temps : on réessaie)
        op.numero = prochain_numero(boutique.id, operateur)
        db.session.add(op)
        try:
            db.session.flush()
            break
        except Exception:
            db.session.rollback()
            db.session.add(op)
    if not caisse_separee(boutique) and de:
        caisse.ajouter(boutique.id, 'mobile_money', de, f"{TYPES[type_]} {COURTS[operateur]} {op.ref}"
                       + (f" · frais {f:,.0f} F".replace(',', ' ') if f else ''), categorie='Mobile money')
        db.session.flush()
        from models import MouvementCaisse
        dernier = (MouvementCaisse.query.filter_by(boutique_id=boutique.id, type='mobile_money')
                   .order_by(MouvementCaisse.id.desc()).first())
        op.mouvement_id = dernier.id if dernier else None
    db.session.commit()
    return op, None


def annuler(op, par=None, motif=None):
    """Annule une opération (erreur de saisie, ou transfert annulé chez l'opérateur : l'argent revient sur le
    solde et le client est remboursé). Ses effets disparaissent des soldes, des caisses et des gains.
    Renvoie None, ou un message d'erreur."""
    if op.annulee:
        return 'Opération déjà annulée'
    if op.type == 'transfert':
        ok, erreur = peut_annuler_transfert(op.boutique, op)
        if not ok:
            return erreur
    op.annulee, op.annulee_par = True, (par or '')[:120] or None
    op.annule_motif = (motif or '').strip()[:200] or None
    if op.mouvement_id:
        from models import MouvementCaisse
        mvt = db.session.get(MouvementCaisse, op.mouvement_id)
        if mvt:
            db.session.delete(mvt)
        op.mouvement_id = None
    db.session.commit()
    return None


def point(boutique, reel_mixx, reel_flooz, reel_especes, par=None):
    """Point de la journée : les soldes réels (lus sur les puces, espèces comptées) comparés au calcul.
    Chaque écart devient un ajustement. Renvoie la liste des écarts [(libellé, calculé, réel, écart)]."""
    s = soldes(boutique.id)
    ecarts = []
    for cle, reel in (('mixx', reel_mixx), ('flooz', reel_flooz), ('especes', reel_especes)):
        r = _nombre(reel)
        if r is None:
            continue
        ecart = round(r - s[cle])
        ecarts.append(('Solde ' + COURTS[cle] if cle in OPERATEURS else 'Espèces du kiosque', s[cle], r, ecart))
        if ecart:
            operateur = cle if cle in OPERATEURS else 'mixx'
            op = OperationMomo(boutique_id=boutique.id, operateur=operateur, type='ajustement', montant=abs(ecart), frais=0,
                               delta_solde=ecart if cle in OPERATEURS else 0, delta_especes=ecart if cle == 'especes' else 0,
                               note=f"Point de la journée : {'Espèces' if cle == 'especes' else COURTS[cle]} "
                                    f"{'+' if ecart > 0 else ''}{ecart:,.0f} F".replace(',', ' '),
                               par=(par or '')[:120] or None, numero=prochain_numero(boutique.id, operateur))
            db.session.add(op)
            db.session.flush()
    db.session.commit()
    return ecarts


def stats(boutique_id, operateur=None, jours=1, maintenant=None):
    """Chiffres d'une période (jours : 1 = aujourd'hui, 7, 30) pour un opérateur ou les deux."""
    maintenant = maintenant or datetime.utcnow()
    debut = datetime.combine((maintenant - timedelta(days=jours - 1)).date(), datetime.min.time())
    q = _valides(boutique_id).filter(OperationMomo.date >= debut)
    if operateur:
        q = q.filter(OperationMomo.operateur == operateur)
    ops = q.all()
    par_type = {t: {'nb': 0, 'montant': 0.0, 'frais': 0.0} for t in TYPES}
    par_vendeur = {}
    for o in ops:
        p = par_type[o.type]
        p['nb'] += 1; p['montant'] += o.montant; p['frais'] += o.frais
        if o.type in CLIENT:
            v = par_vendeur.setdefault(o.par or '—', {'nb': 0, 'frais': 0.0})
            v['nb'] += 1; v['frais'] += o.frais
    clients = [o for o in ops if o.type in CLIENT]
    # Gains des 7 derniers jours (graphique)
    jours7 = []
    for i in range(6, -1, -1):
        j = (maintenant - timedelta(days=i)).date()
        d0 = datetime.combine(j, datetime.min.time())
        qj = _valides(boutique_id).filter(OperationMomo.date >= d0, OperationMomo.date < d0 + timedelta(days=1))
        if operateur:
            qj = qj.filter(OperationMomo.operateur == operateur)
        jours7.append({'jour': j, 'frais': float(qj.with_entities(db.func.coalesce(db.func.sum(OperationMomo.frais), 0)).scalar() or 0)})
    return {'par_type': par_type, 'nb': len(clients), 'volume': sum(o.montant for o in clients),
            'frais': sum(o.frais for o in clients), 'par_vendeur': sorted(par_vendeur.items(), key=lambda x: -x[1]['frais']),
            'jours7': jours7, 'max7': max([x['frais'] for x in jours7] + [1])}


def texte_recu(op):
    b = op.boutique
    lignes = [f"🧾 *{b.nom_boutique}* · {COURTS[op.operateur]}",
              f"{TYPES[op.type]} · réf. {op.ref}" + (f" · SMS {op.sms_ref}" if op.sms_ref else ''),
              f"Date : {op.date.strftime('%d/%m/%Y %H:%M')}",
              f"Montant : {op.montant:,.0f} F".replace(',', ' ')]
    if op.frais:
        lignes.append(f"Frais : {op.frais:,.0f} F".replace(',', ' '))
        lignes.append(f"*Total : {op.montant + op.frais:,.0f} F*".replace(',', ' '))
    if op.type == 'transfert' and op.telephone:
        lignes.append(f"Envoyé au : {op.telephone}")
    lignes += ['', 'Merci ! 🙏']
    return '\n'.join(lignes)
