from flask import Flask, flash, redirect, request, url_for
from flask_login import LoginManager
from sqlalchemy import inspect, text
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix

from models import db, Boutique, Vendeur

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
    colonnes = {c['name'] for c in inspect(db.engine).get_columns('commandes')}
    if 'statut' not in colonnes:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE commandes ADD COLUMN statut VARCHAR(20) NOT NULL DEFAULT 'nouvelle'"))


with app.app_context():
    mettre_a_jour_schema()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
