import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'medilogic-super-secret-key-2025'
    
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    if DATABASE_URL and 'postgresql' in DATABASE_URL:
        # Utiliser psycopg2 (compatible Render)
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///medilogic.db'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # ImgBB API
    IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY') or '72c5c70cf4267dd117cea14606aad030'
    
    # Uploads
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    # Admin global
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL') or ''
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or ''
    
    # WhatsApp
    WHATSAPP_BASE_URL = "https://wa.me/"