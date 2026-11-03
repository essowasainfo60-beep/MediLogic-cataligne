import hmac
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app

from models import db, Boutique

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
        email = request.form.get('email')
        password = request.form.get('password')
        
        cfg = current_app.config
        if (email or '').strip().lower() == cfg['ADMIN_EMAIL'].lower() and                 hmac.compare_digest((password or '').encode(), cfg['ADMIN_PASSWORD'].encode()):
            session['is_admin'] = True
            flash('Connexion administrateur réussie', 'success')
            return redirect(url_for('admin.admin_dashboard'))
        else:
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
    total_boutiques = len(boutiques)
    actives = sum(1 for b in boutiques if b.active)
    inactives = total_boutiques - actives
    
    return render_template('admin/dashboard.html', 
                         boutiques=boutiques,
                         total_boutiques=total_boutiques,
                         actives=actives,
                         inactives=inactives)

@admin_bp.route('/activer/<int:boutique_id>')
@admin_required
def activer_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    boutique.active = True
    db.session.commit()
    flash(f'La boutique "{boutique.nom_boutique}" a été activée', 'success')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/desactiver/<int:boutique_id>')
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