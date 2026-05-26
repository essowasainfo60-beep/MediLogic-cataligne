import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'medilogic-super-secret-key-2025'
    
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    if DATABASE_URL and 'postgresql' in DATABASE_URL:
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///medilogic.db'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Uploads
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    # Admin global
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL') or ''
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or ''
    
    # WhatsApp
    WHATSAPP_BASE_URL = "https://wa.me/"
    
    # Supabase Storage
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY')