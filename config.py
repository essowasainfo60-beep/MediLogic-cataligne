import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'medilogic-super-secret-key-2025'

    # Base Neon (PostgreSQL) en production, SQLite en local si DATABASE_URL absent
    DATABASE_URL = os.environ.get('DATABASE_URL', '')
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = DATABASE_URL if DATABASE_URL.startswith(('postgresql', 'sqlite')) else 'sqlite:///medilogic.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Neon coupe les connexions inactives : on les vérifie avant usage
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_recycle': 280}

    # Uploads : les photos sont compressées puis stockées dans la base
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # total d'un envoi (plusieurs photos)

    # Admin global (identifiants à définir dans l'environnement)
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL') or 'admin@medilogic.com'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or 'Admin@2025MediLogic!'

    # Boutique MB (GBoutik-MediLogic) : encaissement des ventes, complémentaire des commandes livrées
    GBOUTIK_URL = os.environ.get('GBOUTIK_URL') or 'https://gbutik-medilogic.onrender.com/login_page'
