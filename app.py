from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import inspect, text
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from models import db, Boutique, Vendeur, EspaceVendeur, nouveau_code_lien

app = Flask(__name__)
app.config.from_object('config.Config')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # Render : URLs en https

db.init_app(app)
# Chaque formulaire porte un jeton secret : un autre site ne peut pas envoyer
# d'action (confirmer, supprimer, encaisser…) à la place de l'utilisateur.
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'boutique.connexion'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page'


@login_manager.user_loader
def load_user(user_id):
    if user_id.startswith('vendeur_'):
        vendeur = db.session.get(Vendeur, int(user_id.split('_')[1]))
        # Vendeur désactivé ou boutique suspendue : déconnecté à la page suivante
        if vendeur and vendeur.actif and vendeur.boutique.active:
            return EspaceVendeur(vendeur)
        return None
    return db.session.get(Boutique, int(user_id))


from admin_routes import admin_bp
from boutique_routes import boutique_bp
from client_routes import client_bp

app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(boutique_bp, url_prefix='/boutique')
app.register_blueprint(client_bp, url_prefix='/')


@app.errorhandler(RequestEntityTooLarge)
def fichier_trop_gros(e):
    flash('Les photos envoyées sont trop lourdes (32 Mo max au total). Envoyez-en moins à la fois.', 'danger')
    return redirect(request.referrer or url_for('client.accueil'))


@app.errorhandler(CSRFError)
def jeton_invalide(e):
    if request.accept_mimetypes.best == 'application/json' or request.is_json:
        return jsonify(success=False, message='Page expirée, rechargez-la puis réessayez.'), 400
    flash('La page avait expiré : rechargez-la puis recommencez.', 'warning')
    return redirect(request.referrer or url_for('client.accueil'))


@app.errorhandler(404)
def page_introuvable(e):
    return render_template('erreur.html', code=404, titre='Page introuvable',
                           message="Cette page n'existe pas ou n'est plus disponible."), 404


@app.errorhandler(500)
def erreur_serveur(e):
    db.session.rollback()
    return render_template('erreur.html', code=500, titre='Un problème est survenu',
                           message="L'opération n'a pas abouti. Réessayez dans un instant ; rien n'a été enregistré à moitié."), 500


@app.before_request
def vers_domaine_principal():
    """Ouvert par l'adresse Render (…onrender.com) : on bascule sur le domaine officiel,
    pour que les liens envoyés aux clients et aux livreurs portent ce domaine."""
    domaine = app.config.get('DOMAINE_PRINCIPAL')
    hote = request.host.split(':')[0].lower()
    if domaine and hote.endswith('.onrender.com') and request.path != '/sante':
        cible = f"https://{domaine}{request.full_path if request.query_string else request.path}"
        return redirect(cible, code=301 if request.method in ('GET', 'HEAD') else 308)


@app.after_request
def autorisations_navigateur(reponse):
    reponse.headers.setdefault('Permissions-Policy', 'microphone=(self), camera=(self), geolocation=(self)')
    return reponse


@app.context_processor
def dates_formulaires():
    from datetime import datetime, timedelta
    from creneaux import AUTRE
    maintenant = datetime.utcnow()
    return {'aujourdhui_iso': maintenant.strftime('%Y-%m-%d'),
            'dans_30j_iso': (maintenant + timedelta(days=30)).strftime('%Y-%m-%d'), 'creneau_autre': AUTRE}


@app.template_filter('wa')
def filtre_wa(telephone):
    """{{ numero|wa }} : numéro prêt pour un lien wa.me (indicatif +228 ajouté si absent)."""
    import messages_whatsapp
    return messages_whatsapp.numero_wa(telephone)


@app.route('/sante')
def sante():
    """Vérification de bon fonctionnement (Render, surveillance)."""
    db.session.execute(text('SELECT 1'))
    return jsonify(ok=True)


def creer_compte_admin():
    """Premier démarrage : le compte administrateur est créé dans la base à partir de
    ADMIN_EMAIL / ADMIN_PASSWORD. Ensuite, il se modifie depuis la page admin."""
    from models import Administrateur
    if Administrateur.query.first() is None:
        compte = Administrateur(email=app.config['ADMIN_EMAIL'].strip().lower())
        compte.set_mot_de_passe(app.config['ADMIN_PASSWORD'])
        db.session.add(compte)
        db.session.commit()


def mettre_a_jour_schema():
    """Crée les tables manquantes (dont `photos`) et ajoute les colonnes
    récentes sur une base existante, sans toucher aux données."""
    db.create_all()
    inspecteur = inspect(db.engine)
    with db.engine.begin() as conn:
        colonnes_commandes = {c['name'] for c in inspecteur.get_columns('commandes')}
        for nom, definition in [('statut', "VARCHAR(20) NOT NULL DEFAULT 'nouvelle'"),
                                ('latitude', 'FLOAT'), ('longitude', 'FLOAT'),
                                ('livreur_id', 'INTEGER REFERENCES livreurs(id)'),
                                ('code_livraison', 'VARCHAR(32) UNIQUE'),
                                ('date_livraison', 'TIMESTAMP'),
                                ('source', "VARCHAR(30) NOT NULL DEFAULT 'catalogue'"),
                                ('zone_id', 'INTEGER REFERENCES zones(id)'),
                                ('stock_deduit', 'BOOLEAN NOT NULL DEFAULT FALSE'),
                                ('frais_livraison', 'FLOAT NOT NULL DEFAULT 0'),
                                ('reglee', 'BOOLEAN NOT NULL DEFAULT FALSE'),
                                ('date_reglement', 'TIMESTAMP'),
                                ('frais_payes', 'BOOLEAN NOT NULL DEFAULT FALSE'),
                                ('code_suivi', 'VARCHAR(32)'),
                                ('motif_echec', 'VARCHAR(200)'),
                                ('date_echec', 'TIMESTAMP'),
                                ('tentatives', 'INTEGER NOT NULL DEFAULT 0'),
                                ('photo_preuve', 'VARCHAR(300)'),
                                ('creneau', 'VARCHAR(80)'),
                                ('saisie_par', 'VARCHAR(120)'),
                                ('confirmee_par', 'VARCHAR(120)'),
                                ('code_promo', 'VARCHAR(30)'),
                                ('remise', 'FLOAT NOT NULL DEFAULT 0'),
                                ('date_depart', 'TIMESTAMP'),
                                ('date_arrivee', 'TIMESTAMP'),
                                ('livre_par', 'VARCHAR(20)'),
                                ('proposee_at', 'TIMESTAMP'),
                                ('livraison_avant_retrait', 'JSON'),
                                ('mode_frais', 'VARCHAR(20)')]:
            if nom not in colonnes_commandes:
                conn.execute(text(f"ALTER TABLE commandes ADD COLUMN {nom} {definition}"))
        if 'frais' not in {c['name'] for c in inspecteur.get_columns('zones')}:
            conn.execute(text("ALTER TABLE zones ADD COLUMN frais FLOAT NOT NULL DEFAULT 0"))
        colonnes_articles = {c['name'] for c in inspecteur.get_columns('articles')}
        if 'stock' not in colonnes_articles:
            conn.execute(text("ALTER TABLE articles ADD COLUMN stock INTEGER"))
        if 'options' not in colonnes_articles:
            conn.execute(text("ALTER TABLE articles ADD COLUMN options JSON"))
        if 'numero' not in colonnes_articles:
            conn.execute(text("ALTER TABLE articles ADD COLUMN numero INTEGER"))
        for nom in ('variantes', 'photos_choix'):
            if nom not in colonnes_articles:
                conn.execute(text(f"ALTER TABLE articles ADD COLUMN {nom} JSON"))
        if 'stock_par_variante' not in colonnes_articles:
            conn.execute(text("ALTER TABLE articles ADD COLUMN stock_par_variante BOOLEAN NOT NULL DEFAULT FALSE"))
        colonnes_mvt = {c['name'] for c in inspecteur.get_columns('mouvements_stock')}
        if 'variante' not in colonnes_mvt:
            conn.execute(text("ALTER TABLE mouvements_stock ADD COLUMN variante VARCHAR(150)"))
        if 'stock_variante_apres' not in colonnes_mvt:
            conn.execute(text("ALTER TABLE mouvements_stock ADD COLUMN stock_variante_apres INTEGER"))
        # Numérotation propre à chaque boutique (articles et commandes) : 1, 2, 3…
        for table, ordre in [('articles', 'created_at, id'), ('commandes', 'date_commande, id')]:
            champ = 'numero' if table == 'articles' else 'numero_commande'
            for (boutique_id,) in conn.execute(text(f"SELECT DISTINCT boutique_id FROM {table} WHERE {champ} IS NULL")).fetchall():
                dernier = conn.execute(text(f"SELECT COALESCE(MAX({champ}), 0) FROM {table} WHERE boutique_id = :b"),
                                       {'b': boutique_id}).scalar()
                ids = conn.execute(text(f"SELECT id FROM {table} WHERE boutique_id = :b AND {champ} IS NULL ORDER BY {ordre}"),
                                   {'b': boutique_id}).fetchall()
                for i, (ligne_id,) in enumerate(ids, start=dernier + 1):
                    conn.execute(text(f"UPDATE {table} SET {champ} = :n WHERE id = :i"), {'n': i, 'i': ligne_id})
            conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_boutique_{champ} ON {table} (boutique_id, {champ})"))
        colonnes_promo = {c['name'] for c in inspecteur.get_columns('codes_promo')}
        if 'min_articles' not in colonnes_promo:
            conn.execute(text("ALTER TABLE codes_promo ADD COLUMN min_articles INTEGER"))
        if 'une_fois_par_client' not in colonnes_promo:
            conn.execute(text("ALTER TABLE codes_promo ADD COLUMN une_fois_par_client BOOLEAN NOT NULL DEFAULT FALSE"))
        if 'role' not in {c['name'] for c in inspecteur.get_columns('vendeurs')}:
            conn.execute(text("ALTER TABLE vendeurs ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'vendeur'"))
        if inspecteur.has_table('discussions') and 'livreur_id' not in {c['name'] for c in inspecteur.get_columns('discussions')}:
            conn.execute(text("ALTER TABLE discussions ADD COLUMN livreur_id INTEGER REFERENCES livreurs(id) ON DELETE CASCADE"))
        if 'derniere_activite' not in {c['name'] for c in inspecteur.get_columns('vendeurs')}:
            conn.execute(text("ALTER TABLE vendeurs ADD COLUMN derniere_activite TIMESTAMP"))
        if 'par' not in {c['name'] for c in inspecteur.get_columns('mouvements_caisse')}:
            conn.execute(text("ALTER TABLE mouvements_caisse ADD COLUMN par VARCHAR(120)"))
        colonnes_livreurs = {c['name'] for c in inspecteur.get_columns('livreurs')}
        for nom, definition in [('position_lat', 'FLOAT'), ('position_lng', 'FLOAT'), ('position_at', 'TIMESTAMP'),
                                ('disponible', 'BOOLEAN NOT NULL DEFAULT TRUE'),
                                ('externe', 'BOOLEAN NOT NULL DEFAULT FALSE')]:
            if nom not in colonnes_livreurs:
                conn.execute(text(f"ALTER TABLE livreurs ADD COLUMN {nom} {definition}"))
        if 'code_acces' not in {c['name'] for c in inspecteur.get_columns('livreurs')}:
            conn.execute(text("ALTER TABLE livreurs ADD COLUMN code_acces VARCHAR(32)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_livreurs_code_acces ON livreurs (code_acces)"))
        for (livreur_id,) in conn.execute(text("SELECT id FROM livreurs WHERE code_acces IS NULL")).fetchall():
            conn.execute(text("UPDATE livreurs SET code_acces = :c WHERE id = :i"), {'c': nouveau_code_lien(), 'i': livreur_id})
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_commandes_code_suivi ON commandes (code_suivi)"))
        for (commande_id,) in conn.execute(text("SELECT id FROM commandes WHERE code_suivi IS NULL")).fetchall():
            conn.execute(text("UPDATE commandes SET code_suivi = :c WHERE id = :i"), {'c': nouveau_code_lien(), 'i': commande_id})
        colonnes_boutiques = {c['name'] for c in inspecteur.get_columns('boutiques')}
        for nom, definition in [('description', 'TEXT'), ('adresse', 'VARCHAR(255)'),
                                ('mode_frais', "VARCHAR(20) NOT NULL DEFAULT 'livreur_garde'"),
                                ('deconnexion_minutes', 'INTEGER NOT NULL DEFAULT 15'),
                                ('abonnement_prix', 'FLOAT'), ('abonnement_debut', 'VARCHAR(7)'),
                                ('derniere_activite', 'TIMESTAMP'), ('latitude', 'FLOAT'), ('longitude', 'FLOAT'),
                                ('message_statut', 'TEXT'),
                                ('fidelite_actif', 'BOOLEAN NOT NULL DEFAULT FALSE'), ('fidelite_seuil', 'INTEGER'),
                                ('fidelite_type', 'VARCHAR(20)'), ('fidelite_valeur', 'FLOAT'),
                                ('fidelite_mode', 'VARCHAR(20)'), ('fidelite_minimum', 'FLOAT')]:
            if nom not in colonnes_boutiques:
                conn.execute(text(f"ALTER TABLE boutiques ADD COLUMN {nom} {definition}"))
        if 'lien_public' not in colonnes_boutiques:
            conn.execute(text("ALTER TABLE boutiques ADD COLUMN lien_public VARCHAR(32)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_boutiques_lien_public ON boutiques (lien_public)"))
        # Chaque boutique reçoit son code de lien secret
        for (boutique_id,) in conn.execute(text("SELECT id FROM boutiques WHERE lien_public IS NULL")).fetchall():
            conn.execute(text("UPDATE boutiques SET lien_public = :c WHERE id = :i"),
                         {'c': nouveau_code_lien(), 'i': boutique_id})


with app.app_context():
    mettre_a_jour_schema()
    creer_compte_admin()


# ==================== APPLICATION INSTALLABLE (PWA) ====================

@app.route('/app-manifest.json')
def app_manifest():
    return send_from_directory('static', 'app-manifest.json', mimetype='application/manifest+json')


@app.route('/sw.js')
def service_worker():
    reponse = send_from_directory('static', 'sw.js', mimetype='application/javascript')
    reponse.headers['Cache-Control'] = 'no-cache'
    return reponse


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
