"""Pages de l'espace « Mixx & Flooz » (voir momo.py). Routes ajoutées au blueprint boutique."""
import csv
import io
from datetime import datetime

from flask import Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

import abonnement
import messages_whatsapp as msg
import momo
from boutique_routes import (boutique_bp, boutique_connectee, qui, peut, MODULE_BOUTIQUE, GERANT_SEUL, CAISSE, _bornes)
from models import db, OperationMomo

PAGES = {'momo_accueil', 'momo_operateur', 'momo_operation', 'momo_detail', 'momo_photo', 'momo_annuler',
         'momo_caisses', 'momo_point', 'momo_reglages', 'momo_journal_csv', 'momo_historique', 'momo_recu'}
MODULE_BOUTIQUE.update(PAGES)            # formules avec la vente au comptoir (Pro, Premium…)
GERANT_SEUL.add('momo_reglages')
CAISSE.add('momo_annuler')               # annuler : gérant, caissier, gestionnaire


def _op(operateur):
    if operateur not in momo.OPERATEURS:
        abort(404)
    return operateur


def _operation(op_id):
    o = db.session.get(OperationMomo, op_id)
    if not o or o.boutique_id != boutique_connectee().id:
        abort(404)
    return o


def _fcfa(n):
    return f"{n or 0:,.0f} F".replace(',', ' ')


@boutique_bp.route('/momo')
@login_required
def momo_accueil():
    b = boutique_connectee()
    s = momo.soldes(b.id)
    jour = momo.stats(b.id, None, 1)
    dernieres = (OperationMomo.query.filter_by(boutique_id=b.id).order_by(OperationMomo.date.desc()).limit(8).all())
    return render_template('boutique/momo_accueil.html', s=s, seuil=momo.seuil(b), jour=jour, dernieres=dernieres,
                           operateurs=momo.OPERATEURS, courts=momo.COURTS, types=momo.TYPES, fcfa=_fcfa)


@boutique_bp.route('/momo/<operateur>')
@login_required
def momo_operateur(operateur):
    b = boutique_connectee()
    _op(operateur)
    return render_template('boutique/momo_operateur.html', op=operateur, nom=momo.OPERATEURS[operateur],
                           court=momo.COURTS[operateur], s=momo.soldes(b.id), fcfa=_fcfa,
                           marchand=momo.a_code_marchand(b, operateur))


@boutique_bp.route('/momo/<operateur>/<type_>', methods=['GET', 'POST'])
@login_required
def momo_operation(operateur, type_):
    b = boutique_connectee()
    _op(operateur)
    if type_ not in ('depot', 'retrait', 'transfert', 'recharge'):
        abort(404)
    if request.method == 'POST':
        f = request.form
        photo, erreur = abonnement.lire_preuve(request.files.get('photo'))
        op = None
        if not erreur:
            op, erreur = momo.enregistrer(b, operateur, type_, f.get('montant'), telephone=f.get('telephone'),
                                          sms_ref=f.get('sms_ref'), appliquer_frais=bool(f.get('appliquer')),
                                          frais=f.get('frais'), client_telephone=f.get('client_telephone'),
                                          paye_caisse=bool(f.get('paye_caisse')), photo=photo, par=qui() or b.nom_boutique,
                                          note=f.get('note'), marchand=bool(f.get('marchand')))
        if erreur:
            flash(erreur, 'danger')
            return render_template('boutique/momo_operation.html', **_contexte_operation(b, operateur, type_), saisie=f), 400
        return redirect(url_for('boutique.momo_detail', op_id=op.id, nouveau=1))
    return render_template('boutique/momo_operation.html', **_contexte_operation(b, operateur, type_), saisie={})


def _contexte_operation(b, operateur, type_):
    return {'op': operateur, 'type_': type_, 'nom': momo.OPERATEURS[operateur], 'court': momo.COURTS[operateur],
            'libelle': momo.TYPES[type_], 's': momo.soldes(b.id), 'grille': momo.grilles(b)[operateur],
            'ref_auto': ('MX-' if operateur == 'mixx' else 'FL-') + f'{momo.prochain_numero(b.id, operateur):04d}',
            'marchand': momo.a_code_marchand(b, operateur), 'fcfa': _fcfa}


@boutique_bp.route('/momo/operation/<int:op_id>')
@login_required
def momo_detail(op_id):
    o = _operation(op_id)
    lien_wa = msg.lien_whatsapp(o.client_telephone or o.telephone, momo.texte_recu(o)) \
        if (o.client_telephone or o.telephone) and o.type in momo.CLIENT else None
    peut_annuler, raison = (momo.peut_annuler_transfert(o.boutique, o) if o.type == 'transfert' else (True, None))
    return render_template('boutique/momo_detail.html', o=o, s=momo.soldes(o.boutique_id), lien_wa=lien_wa,
                           nouveau=request.args.get('nouveau'), types=momo.TYPES, courts=momo.COURTS, fcfa=_fcfa,
                           annulable=peut('boutique.momo_annuler') and not o.annulee and o.type != 'ajustement',
                           peut_annuler=peut_annuler, raison=raison)


@boutique_bp.route('/momo/operation/<int:op_id>/recu')
@login_required
def momo_recu(op_id):
    """Reçu de la transaction, au format ticket (imprimante 80 mm ou A4), à remettre au client."""
    o = _operation(op_id)
    tel = o.client_telephone or o.telephone
    lien_wa = msg.lien_whatsapp(tel, momo.texte_recu(o)) if tel and o.type in momo.CLIENT and not o.annulee else None
    return render_template('boutique/momo_recu.html', o=o, lien_wa=lien_wa, nom_op=momo.COURTS[o.operateur],
                           type_libelle=momo.TYPES[o.type])


def _filtre_historique(b, args):
    q = OperationMomo.query.filter_by(boutique_id=b.id)
    du, au = _bornes(args.get('du'), args.get('au'))
    if du:
        q = q.filter(OperationMomo.date >= du)
    if au:
        q = q.filter(OperationMomo.date < au)
    if args.get('operateur') in momo.OPERATEURS:
        q = q.filter_by(operateur=args['operateur'])
    if args.get('type') in momo.TYPES:
        q = q.filter_by(type=args['type'])
    if args.get('etat') == 'annulees':
        q = q.filter(OperationMomo.annulee.is_(True))
    elif args.get('etat') != 'toutes':
        q = q.filter(OperationMomo.annulee.is_(False))
    cherche = (args.get('q') or '').strip()
    if cherche:
        chiffres = ''.join(c for c in cherche if c.isdigit())
        motif = f'%{cherche.upper()}%'
        conditions = [db.func.upper(OperationMomo.sms_ref).like(motif), db.func.upper(OperationMomo.note).like(motif)]
        if chiffres:
            conditions += [OperationMomo.telephone.like(f'%{chiffres}%'), OperationMomo.client_telephone.like(f'%{chiffres}%')]
        ref = cherche.upper().replace(' ', '')
        if ref[:3] in ('MX-', 'FL-') and ref[3:].isdigit():
            conditions.append(db.and_(OperationMomo.operateur == ('mixx' if ref.startswith('MX') else 'flooz'),
                                      OperationMomo.numero == int(ref[3:])))
        q = q.filter(db.or_(*conditions))
    return q


@boutique_bp.route('/momo/historique')
@login_required
def momo_historique():
    """Historique des transactions : filtres (date et heure, opérateur, opération, recherche), reçus."""
    b = boutique_connectee()
    ops = _filtre_historique(b, request.args).order_by(OperationMomo.date.desc()).limit(500).all()
    clients = [o for o in ops if o.type in momo.CLIENT and not o.annulee]
    totaux = {'nb': len(ops), 'montant': sum(o.montant for o in clients), 'frais': sum(o.frais for o in clients)}
    return render_template('boutique/momo_historique.html', ops=ops, f=request.args, totaux=totaux, types=momo.TYPES,
                           courts=momo.COURTS, operateurs=momo.OPERATEURS, fcfa=_fcfa)


@boutique_bp.route('/momo/operation/<int:op_id>/photo')
@login_required
def momo_photo(op_id):
    o = _operation(op_id)
    if not o.photo_mime or not o.photo:
        abort(404)
    r = Response(o.photo, mimetype=o.photo_mime)
    r.headers['Cache-Control'] = 'private, max-age=3600'
    r.headers['X-Content-Type-Options'] = 'nosniff'
    return r


@boutique_bp.route('/momo/operation/<int:op_id>/annuler', methods=['POST'])
@login_required
def momo_annuler(op_id):
    o = _operation(op_id)
    erreur = momo.annuler(o, par=qui(), motif=request.form.get('motif'))
    if erreur:
        flash(erreur, 'danger')
    else:
        flash(f"{momo.TYPES[o.type]} {o.ref} annulé" + (" : l'argent revient sur le solde, remboursez le client en espèces."
                                                       if o.type == 'transfert' else '.'), 'warning')
    return redirect(url_for('boutique.momo_detail', op_id=o.id))


PERIODES = {'jour': (1, "Aujourd'hui"), 'semaine': (7, '7 jours'), 'mois': (30, '30 jours')}


@boutique_bp.route('/momo/caisses')
@login_required
def momo_caisses():
    b = boutique_connectee()
    onglet = request.args.get('voir') if request.args.get('voir') in momo.OPERATEURS else 'ensemble'
    periode = request.args.get('periode') if request.args.get('periode') in PERIODES else 'jour'
    st = momo.stats(b.id, None if onglet == 'ensemble' else onglet, PERIODES[periode][0])
    q = OperationMomo.query.filter_by(boutique_id=b.id)
    if onglet != 'ensemble':
        q = q.filter_by(operateur=onglet)
    journal = q.order_by(OperationMomo.date.desc()).limit(200).all()
    return render_template('boutique/momo_caisses.html', st=st, s=momo.soldes(b.id), onglet=onglet, periode=periode,
                           periodes=PERIODES, journal=journal, types=momo.TYPES, courts=momo.COURTS, fcfa=_fcfa,
                           separee=momo.caisse_separee(b), operateurs=momo.OPERATEURS)


@boutique_bp.route('/momo/journal.csv')
@login_required
def momo_journal_csv():
    b = boutique_connectee()
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=';')
    w.writerow(['Date', 'Référence', 'Opérateur', 'Opération', 'Montant', 'Frais', 'Code marchand', 'Téléphone',
                'Référence SMS', 'Par', 'Annulée', 'Motif'])
    for o in _filtre_historique(b, request.args.to_dict() | {'etat': request.args.get('etat') or 'toutes'}).order_by(OperationMomo.date.desc()).all():
        w.writerow([o.date.strftime('%d/%m/%Y %H:%M'), o.ref, momo.COURTS[o.operateur], momo.TYPES[o.type],
                    f'{o.montant:.0f}', f'{o.frais:.0f}', 'oui' if o.marchand else '', o.telephone or '', o.sms_ref or '',
                    o.par or '', 'oui' if o.annulee else '', o.annule_motif or o.note or ''])
    return Response('﻿' + sortie.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="mixx-flooz-{datetime.utcnow():%Y%m%d}.csv"'})


@boutique_bp.route('/momo/point', methods=['GET', 'POST'])
@login_required
def momo_point():
    b = boutique_connectee()
    ecarts = None
    if request.method == 'POST':
        ecarts = momo.point(b, request.form.get('mixx'), request.form.get('flooz'), request.form.get('especes'),
                            par=qui() or b.nom_boutique)
        flash('Point enregistré' + (' : écarts corrigés' if any(e[3] for e in ecarts) else ' : tout est juste 👍'), 'success')
    return render_template('boutique/momo_point.html', s=momo.soldes(b.id), ecarts=ecarts, fcfa=_fcfa)


@boutique_bp.route('/momo/reglages', methods=['GET', 'POST'])
@login_required
def momo_reglages():
    b = boutique_connectee()
    if request.method == 'POST':
        f = request.form
        nouvelles = {}
        try:
            for op in momo.OPERATEURS:
                lignes = []
                for maxi, frais in zip(f.getlist(f'{op}_max'), f.getlist(f'{op}_frais')):
                    if not (maxi or '').strip():
                        continue
                    lignes.append([int(float(maxi.replace(' ', ''))), int(float((frais or '0').replace(' ', '')))])
                lignes.sort()
                if any(m <= 0 or fr < 0 for m, fr in lignes):
                    raise ValueError
                nouvelles[op] = lignes or momo.GRILLES_DEFAUT[op]
            seuil = int(float((f.get('seuil') or '0').replace(' ', '')))
            annulation = {op: (int(float(f.get(f'annulation_{op}').replace(' ', ''))) if (f.get(f'annulation_{op}') or '').strip() else None)
                          for op in momo.OPERATEURS}
        except (TypeError, ValueError):
            flash('Des montants sont invalides (nombres positifs seulement)', 'danger')
            return redirect(url_for('boutique.momo_reglages'))
        b.momo_grilles = nouvelles
        b.momo_seuil = max(seuil, 0)
        b.momo_caisse = 'boutique' if f.get('caisse') == 'boutique' else 'separee'
        b.momo_reglages = {'marchand': {op: bool(f.get(f'marchand_{op}')) for op in momo.OPERATEURS},
                           'annulation_max': annulation}
        db.session.commit()
        flash('Réglages Mixx & Flooz enregistrés', 'success')
        return redirect(url_for('boutique.momo_reglages'))
    return render_template('boutique/momo_reglages.html', grilles=momo.grilles(b), seuil=momo.seuil(b),
                           separee=momo.caisse_separee(b), r=momo.reglages(b), operateurs=momo.OPERATEURS, fcfa=_fcfa)
