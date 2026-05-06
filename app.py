import os
from flask import Flask, render_template, redirect, url_for, flash, request, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, Boutique, Vendeur, Article, Commande
from utils import upload_to_imgbb, upload_multiple_images
from datetime import datetime
from models import db

app = Flask(__name__)
app.config.from_object('config.Config')

# Initialisation de la base de données
db.init_app(app)

# Configuration de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'boutique.connexion'  # ← Change ici
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page'

@login_manager.user_loader
def load_user(user_id):
    # Gérer les vendeurs si nécessaire
    if user_id.startswith('vendeur_'):
        vendeur_id = int(user_id.split('_')[1])
        return Vendeur.query.get(vendeur_id)
    else:
        return Boutique.query.get(int(user_id))

# Import des routes (après création des fichiers)
from admin_routes import admin_bp
from boutique_routes import boutique_bp
from client_routes import client_bp

app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(boutique_bp, url_prefix='/boutique')
app.register_blueprint(client_bp, url_prefix='/')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Créer le compte admin global s'il n'existe pas déjà
        from werkzeug.security import generate_password_hash
        admin = Boutique.query.filter_by(email=app.config['ADMIN_EMAIL']).first()
        if not admin and app.config['ADMIN_EMAIL'] != 'admin@medilogic.com':
            # En production, l'admin n'est pas une boutique mais un vrai admin
            pass
    
    app.run(debug=True, host='0.0.0.0', port=5000)