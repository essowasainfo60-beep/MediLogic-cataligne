import io
import re

from PIL import Image, ImageOps
from flask import url_for

from models import db, Photo

# Les photos sont stockées directement dans la base Neon (colonne bytea),
# comme les fichiers et signatures de GHP. On les réduit avant stockage pour
# garder la base légère : 1280 px max, JPEG qualité 80 (~100-250 Ko/photo).
TAILLE_MAX_PX = 1280
TAILLE_LOGO_PX = 400
QUALITE_JPEG = 80

PHOTO_URL_RE = re.compile(r'^/photo/(\d+)$')


def compresser_image(fichier, taille_max=TAILLE_MAX_PX):
    """Retourne (octets, mime) d'une image redimensionnée et compressée,
    ou None si le fichier n'est pas une image lisible."""
    try:
        img = Image.open(fichier)
        img = ImageOps.exif_transpose(img)  # photos de téléphone : respecte l'orientation
        img.thumbnail((taille_max, taille_max), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        if img.mode in ('RGBA', 'LA', 'P') and taille_max <= TAILLE_LOGO_PX:
            # Logo : on garde la transparence en PNG
            img.save(buffer, format='PNG', optimize=True)
            return buffer.getvalue(), 'image/png'

        if img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(buffer, format='JPEG', quality=QUALITE_JPEG, optimize=True, progressive=True)
        return buffer.getvalue(), 'image/jpeg'
    except Exception as e:
        print(f"Image illisible ({getattr(fichier, 'filename', '?')}): {e}")
        return None


def enregistrer_photo(fichier, boutique_id, taille_max=TAILLE_MAX_PX):
    """Enregistre une image en base et retourne son URL (/photo/<id>), ou None."""
    if not fichier or not fichier.filename:
        return None
    resultat = compresser_image(fichier, taille_max)
    if not resultat:
        return None
    donnees, mime = resultat
    photo = Photo(boutique_id=boutique_id, donnees=donnees, mime=mime)
    db.session.add(photo)
    db.session.flush()  # attribue l'id sans valider la transaction
    return url_for('client.photo', photo_id=photo.id)


def enregistrer_photos(fichiers, boutique_id):
    """Enregistre plusieurs images. Retourne (urls, nombre_d_echecs)."""
    urls, echecs = [], 0
    for fichier in fichiers:
        if not fichier or not fichier.filename:
            continue
        url = enregistrer_photo(fichier, boutique_id)
        if url:
            urls.append(url)
        else:
            echecs += 1
    return urls, echecs


def supprimer_photo_stockee(url, boutique_id):
    """Supprime de la base la photo derrière une URL /photo/<id>.
    Les anciennes URLs externes (ImgBB, Supabase) sont simplement ignorées."""
    m = PHOTO_URL_RE.match(url or '')
    if m:
        Photo.query.filter_by(id=int(m.group(1)), boutique_id=boutique_id).delete()
