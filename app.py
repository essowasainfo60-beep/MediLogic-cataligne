from flask import Flask, flash, redirect, request, send_from_directory, url_for
from flask_login import LoginManager
from sqlalchemy import inspect, text
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from models import db, Boutique, Vendeur, nouveau_code_lien

app = Flask(__name__)
app.config.from_object('config.Config')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # Render : URLs en https

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'boutique.connexion'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page'


@login_manager.user_loader
def load_user(user_id):
    if user_id.startswith('vendeur_'):
        return db.session.get(Vendeur, int(user_id.split('_')[1]))
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
                                ('frais_livraison', 'FLOAT NOT NULL DEFAULT 0')]:
            if nom not in colonnes_commandes:
                conn.execute(text(f"ALTER TABLE commandes ADD COLUMN {nom} {definition}"))
        if 'frais' not in {c['name'] for c in inspecteur.get_columns('zones')}:
            conn.execute(text("ALTER TABLE zones ADD COLUMN frais FLOAT NOT NULL DEFAULT 0"))
        if 'stock' not in {c['name'] for c in inspecteur.get_columns('articles')}:
            conn.execute(text("ALTER TABLE articles ADD COLUMN stock INTEGER"))
        if 'lien_public' not in {c['name'] for c in inspecteur.get_columns('boutiques')}:
            conn.execute(text("ALTER TABLE boutiques ADD COLUMN lien_public VARCHAR(32)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_boutiques_lien_public ON boutiques (lien_public)"))
        # Chaque boutique reçoit son code de lien secret
        for (boutique_id,) in conn.execute(text("SELECT id FROM boutiques WHERE lien_public IS NULL")).fetchall():
            conn.execute(text("UPDATE boutiques SET lien_public = :c WHERE id = :i"),
                         {'c': nouveau_code_lien(), 'i': boutique_id})


with app.app_context():
    mettre_a_jour_schema()


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
