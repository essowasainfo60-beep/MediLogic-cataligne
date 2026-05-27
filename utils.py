import os
import time
from PIL import Image
import io
import requests
from werkzeug.utils import secure_filename
from flask import current_app

def compress_image(file, max_size_mb=10):
    """Compresse une image avant upload"""
    try:
        img = Image.open(file)
        
        # Convertir en RGB si nécessaire (pour PNG avec transparence)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Redimensionner si trop grande (max 2000px)
        if img.width > 2000 or img.height > 2000:
            ratio = min(2000/img.width, 2000/img.height)
            new_size = (int(img.width*ratio), int(img.height*ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Compresser
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=75, optimize=True)
        buffer.seek(0)
        
        return buffer
    except Exception as e:
        print(f"Erreur compression: {e}")
        return file

def upload_to_imgbb(file, custom_name=None):
    """Upload vers Supabase avec compression"""
    try:
        supabase_url = current_app.config.get('SUPABASE_URL')
        supabase_key = current_app.config.get('SUPABASE_KEY')
        
        if not supabase_url or not supabase_key:
            return None
        
        # Compresser l'image
        compressed_file = compress_image(file)
        
        # Ajouter un timestamp pour éviter les doublons
        timestamp = int(time.time())
        original_name = secure_filename(custom_name or file.filename)
        name, ext = os.path.splitext(original_name)
        filename = f"{name}_{timestamp}{ext}"
        
        # Upload vers Supabase
        file_path = f"articles/{filename}"
        
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}"
        }
        
        files = {'file': (filename, compressed_file, 'image/jpeg')}
        
        upload_url = f"{supabase_url}/storage/v1/object/mediLogic-images/{file_path}"
        response = requests.post(upload_url, headers=headers, files=files)
        
        if response.status_code in [200, 201]:
            public_url = f"{supabase_url}/storage/v1/object/public/mediLogic-images/{file_path}"
            print(f"✅ Image uploadée sur Supabase: {public_url}")
            return public_url
        else:
            print(f"❌ Erreur: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None

def upload_multiple_images(files, boutique_id, article_id=None):
    urls = []
    for idx, file in enumerate(files):
        if file and file.filename:
            custom_name = f"boutique_{boutique_id}_article_{article_id or idx}_{idx}"
            url = upload_to_imgbb(file, custom_name)
            if url:
                urls.append(url)
    return urls