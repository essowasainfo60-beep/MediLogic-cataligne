import hmac
import re
from datetime import date
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app

import abonnement
import securite
from models import db, Boutique, Commande, Article, PaiementAbonnement
import messages_whatsapp as msg

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Accès réservé à l\'administrateur', 'danger')
            return redirect(url_for('admin.admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('is_admin'):
        return redirect(url_for('admin.admin_dashboard'))
    
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        attente = securite.bloque(request, 'admin')
        if attente:
            flash(f'Trop d\'essais incorrects. Réessayez dans {attente} minute(s).', 'danger')
            return render_template('admin/login.html'), 429

        cfg = current_app.config
        if email == cfg['ADMIN_EMAIL'].lower() and hmac.compare_digest(password.encode(), cfg['ADMIN_PASSWORD'].encode()):
            securite.succes(request, 'admin')
            session['is_admin'] = True
            flash('Connexion administrateur réussie', 'success')
            return redirect(url_for('admin.admin_dashboard'))
        else:
            securite.echec(request, 'admin')
            flash('Email ou mot de passe incorrect', 'danger')
    
    return render_template('admin/login.html')

@admin_bp.route('/logout')
def admin_logout():
    session.pop('is_admin', None)
    flash('Déconnexion réussie', 'success')
    return redirect(url_for('admin.admin_login'))

@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    boutiques = Boutique.query.order_by(Boutique.date_inscription.desc()).all()
    mois = abonnement.cle_mois(date.today())
    fiches = []
    for b in boutiques:
        activites = [d for d in [b.derniere_activite] + [v.derniere_activite for v in b.vendeurs] if d]
        derniere_commande = (db.session.query(db.func.max(Commande.date_commande)).filter_by(boutique_id=b.id).scalar())
        fiches.append({
            'b': b, 'etat': abonnement.etat(b),
            'derniere_activite': max(activites) if activites else None,
            'derniere_commande': derniere_commande,
            'nb_commandes': Commande.query.filter_by(boutique_id=b.id).count(),
            'nb_articles': Article.query.filter_by(boutique_id=b.id, archive=False).count(),
            'equipe': len([v for v in b.vendeurs if v.actif]),
        })
    payantes = [f for f in fiches if f['etat']['exige']]
    paiements = PaiementAbonnement.query.order_by(PaiementAbonnement.created_at.desc()).limit(100).all()
    resume = {
        'total': len(boutiques), 'actives': sum(1 for b in boutiques if b.active),
        'a_jour': sum(1 for f in payantes if f['etat']['niveau'] == 'ok'),
        'en_attente': sum(1 for f in payantes if f['etat']['niveau'] in ('jaune', 'orange', 'rouge')),
        'bloquees': sum(1 for f in payantes if f['etat']['bloque']),
        'attendu': sum(f['etat']['prix'] for f in payantes),
        'encaisse_mois': sum(p.montant for p in paiements if p.statut == 'valide' and p.mois == mois),
    }
    return render_template('admin/dashboard.html', fiches=fiches, resume=resume, paiements=paiements,
                           fcfa=msg.fcfa, mois_libelle=abonnement.libelle_mois(mois),
                           premier_mois=abonnement.premier_mois_par_defaut(), modes=PaiementAbonnement.MODES)


@admin_bp.route('/abonnement/<int:boutique_id>', methods=['POST'])
@admin_required
def regler_abonnement(boutique_id):
    """Prix mensuel et premier mois facturé d'une boutique."""
    boutique = Boutique.query.get_or_404(boutique_id)
    try:
        prix = float((request.form.get('prix') or '0').replace(' ', '').replace(',', '.'))
    except ValueError:
        prix = -1
    debut = (request.form.get('debut') or '').strip()
    if prix < 0 or (debut and not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])', debut)):
        flash('Prix ou mois de début invalide', 'danger')
        return redirect(url_for('admin.admin_dashboard'))
    boutique.abonnement_prix = prix or None
    boutique.abonnement_debut = (debut or boutique.abonnement_debut or abonnement.premier_mois_par_defaut()) if prix else None
    db.session.commit()
    if prix:
        flash(f"{boutique.nom_boutique} : {msg.fcfa(prix)} par mois à partir de "
              f"{abonnement.libelle_mois(boutique.abonnement_debut)}", 'success')
    else:
        flash(f"{boutique.nom_boutique} : aucun abonnement à payer", 'success')
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/abonnement/<int:boutique_id>/encaisser', methods=['POST'])
@admin_required
def encaisser_abonnement(boutique_id):
    """L'administrateur enregistre lui-même un paiement reçu (espèces, dépôt vérifié…)."""
    boutique = Boutique.query.get_or_404(boutique_id)
    mode = request.form.get('mode') or 'especes'
    paiement, erreur = abonnement.enregistrer(boutique, mode, request.form.get('reference'), date.today(),
                                              par='Administrateur LivraPlus')
    if erreur:
        flash(f'{boutique.nom_boutique} : {erreur}', 'danger')
    else:
        flash(f'{boutique.nom_boutique} : {paiement.mois_libelle} payé ({msg.fcfa(paiement.montant)})', 'success')
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/paiement/<int:paiement_id>/annuler', methods=['POST'])
@admin_required
def annuler_paiement(paiement_id):
    """Référence fausse ou dépôt non reçu : le mois redevient dû (et la charge disparaît de la caisse)."""
    paiement = PaiementAbonnement.query.get_or_404(paiement_id)
    abonnement.annuler(paiement)
    flash(f'Paiement de {paiement.boutique.nom_boutique} ({paiement.mois_libelle}) annulé', 'warning')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/activer/<int:boutique_id>', methods=['POST'])
@admin_required
def activer_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    boutique.active = True
    db.session.commit()
    flash(f'La boutique "{boutique.nom_boutique}" a été activée', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/desactiver/<int:boutique_id>', methods=['POST'])
@admin_required
def desactiver_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    boutique.active = False
    db.session.commit()
    flash(f'La boutique "{boutique.nom_boutique}" a été désactivée', 'warning')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/reinitialiser_mdp/<int:boutique_id>', methods=['GET', 'POST'])
@admin_required
def reinitialiser_mdp(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    
    if request.method == 'POST':
        nouveau_mdp = request.form.get('nouveau_mdp')
        if nouveau_mdp and len(nouveau_mdp) >= 8:
            boutique.set_mot_de_passe(nouveau_mdp)
            db.session.commit()
            flash(f'Mot de passe réinitialisé pour {boutique.nom_boutique}', 'success')
            return redirect(url_for('admin.admin_dashboard'))
        else:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'danger')
    
    return render_template('admin/reinitialiser_mdp.html', boutique=boutique)

@admin_bp.route('/supprimer/<int:boutique_id>', methods=['POST'])
@admin_required
def supprimer_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    db.session.delete(boutique)  # supprime aussi articles, photos, vendeurs et commandes
    db.session.commit()
    flash(f'La boutique "{boutique.nom_boutique}" a été supprimée', 'danger')
    return redirect(url_for('admin.admin_dashboard'))