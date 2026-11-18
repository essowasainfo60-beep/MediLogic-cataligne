"""Vidéos courtes des articles, stockées dans la base (comme les photos).

  - La boutique envoie la vidéo à part (barre de progression), avant d'enregistrer l'article.
  - Si ffmpeg est disponible (paquet imageio-ffmpeg), la vidéo est recompressée en arrière-plan :
    720p, H.264/AAC, MP4 lisible par TOUS les téléphones (les vidéos d'iPhone en HEVC ne passent
    pas sur beaucoup d'Android), et 5 à 10 fois plus légère (moins de place dans Neon,
    moins de forfait internet pour les clients).
  - Lecture par morceaux (requêtes « Range ») : indispensable pour l'iPhone, et seuls les
    octets demandés sont lus dans la base."""
import logging
import os
import re
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta

from flask import Response, abort, current_app, request, url_for

from models import db, Video

log = logging.getLogger(__name__)

TAILLE_MAX = 30 * 1024 * 1024          # 30 Mo envoyés au plus
DUREE_MAX = 30                         # secondes (vérifié aussi sur le téléphone avant l'envoi)
TYPES = {'video/mp4': 'video/mp4', 'video/quicktime': 'video/quicktime', 'video/webm': 'video/webm',
         'video/x-m4v': 'video/mp4', 'video/3gpp': 'video/3gpp'}
VIDEO_URL_RE = re.compile(r'^/video/(\d+)$')


def ffmpeg():
    """Chemin de ffmpeg, ou None (la vidéo est alors gardée telle quelle)."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        from shutil import which
        return which('ffmpeg')


def enregistrer(fichier, boutique_id, duree=None):
    """Enregistre la vidéo envoyée. Renvoie (video, erreur)."""
    if not fichier or not fichier.filename:
        return None, 'Aucune vidéo reçue'
    mime = TYPES.get((fichier.mimetype or '').lower())
    if not mime:
        return None, "Ce fichier n'est pas une vidéo (MP4, MOV ou WebM)"
    donnees = fichier.read(TAILLE_MAX + 1)
    if len(donnees) > TAILLE_MAX:
        return None, f'Vidéo trop lourde (30 Mo au plus) : filmez moins longtemps ou en 720p'
    if len(donnees) < 1000:
        return None, 'Vidéo vide ou illisible'
    try:
        duree = round(float(duree)) if duree else None
    except (TypeError, ValueError):
        duree = None
    if duree and duree > DUREE_MAX + 1:
        return None, f'Vidéo trop longue ({duree} s) : {DUREE_MAX} secondes au plus'
    _nettoyer(boutique_id)
    video = Video(boutique_id=boutique_id, donnees=donnees, mime=mime, taille=len(donnees), duree=duree,
                  statut='a_compresser' if ffmpeg() else 'prete')
    db.session.add(video)
    db.session.commit()
    if video.statut == 'a_compresser':
        lancer_compression(video.id)
    return video, None


def _nettoyer(boutique_id):
    """Vidéos envoyées mais jamais rattachées à un article (formulaire abandonné) depuis plus d'un jour."""
    Video.query.filter(Video.boutique_id == boutique_id, Video.article_id.is_(None),
                       Video.created_at < datetime.utcnow() - timedelta(days=1)).delete(synchronize_session=False)


def lancer_compression(video_id):
    app = current_app._get_current_object()
    if app.config.get('TESTING') or app.config.get('VIDEO_SYNCHRONE'):
        compresser(video_id)
        return
    threading.Thread(target=_compresser_avec_app, args=(app, video_id), daemon=True).start()


def _compresser_avec_app(app, video_id):
    with app.app_context():
        try:
            compresser(video_id)
        except Exception:
            log.exception('Compression vidéo %s impossible', video_id)
            db.session.rollback()


def compresser(video_id):
    """720p max, H.264 + AAC, « faststart » (lecture avant la fin du téléchargement).
    Garde l'original si la compression échoue ou n'allège pas."""
    video = db.session.get(Video, video_id)
    exe = ffmpeg()
    if not video or not exe:
        if video:
            video.statut = 'prete'
            db.session.commit()
        return
    with tempfile.TemporaryDirectory() as dossier:
        entree, sortie = os.path.join(dossier, 'entree'), os.path.join(dossier, 'sortie.mp4')
        with open(entree, 'wb') as f:
            f.write(video.donnees)
        commande = [exe, '-y', '-loglevel', 'error', '-i', entree, '-t', str(DUREE_MAX + 1),
                    '-vf', "scale='min(1280,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', sortie]
        try:
            subprocess.run(commande, check=True, timeout=300, capture_output=True)
            with open(sortie, 'rb') as f:
                nouvelles = f.read()
        except Exception as e:
            log.warning('Compression vidéo %s échouée : %s', video_id, e)
            nouvelles = None
    video = db.session.get(Video, video_id)        # relue : la session a pu changer entre-temps
    if video is None:
        return
    if nouvelles and len(nouvelles) > 1000 and (len(nouvelles) < video.taille or video.mime != 'video/mp4'):
        video.donnees, video.mime, video.taille = nouvelles, 'video/mp4', len(nouvelles)
    video.statut = 'prete'
    db.session.commit()


def url(video):
    return url_for('client.video', video_id=video.id)


def de_url(url_video, boutique_id):
    m = VIDEO_URL_RE.match(url_video or '')
    if not m:
        return None
    return Video.query.filter_by(id=int(m.group(1)), boutique_id=boutique_id).first()


def rattacher(article, video_id):
    """Met la vidéo (déjà envoyée) sur l'article ; l'ancienne est supprimée."""
    try:
        video = Video.query.filter_by(id=int(video_id), boutique_id=article.boutique_id).first()
    except (TypeError, ValueError):
        video = None
    if not video:
        return False
    if article.video_url and article.video_url != url(video):
        retirer(article)
    video.article_id = article.id
    article.video_url = url(video)
    return True


def retirer(article):
    ancienne = de_url(article.video_url, article.boutique_id)
    if ancienne:
        db.session.delete(ancienne)
    article.video_url = None


def servir(video_id):
    """Réponse HTTP avec gestion des morceaux (Range) : seuls les octets demandés sont lus en base."""
    infos = db.session.query(Video.taille, Video.mime).filter(Video.id == video_id).first()
    if not infos:
        abort(404)
    taille, mime = infos
    debut, fin = 0, taille - 1
    plage = request.headers.get('Range', '')
    m = re.match(r'bytes=(\d*)-(\d*)$', plage.strip())
    partiel = bool(m and (m.group(1) or m.group(2)))
    if partiel:
        if m.group(1):
            debut = int(m.group(1))
            fin = min(int(m.group(2)), taille - 1) if m.group(2) else min(debut + 2 * 1024 * 1024 - 1, taille - 1)
        else:                                       # « bytes=-500 » : les 500 derniers octets
            debut = max(0, taille - int(m.group(2)))
        if debut >= taille or debut > fin:
            r = Response(status=416)
            r.headers['Content-Range'] = f'bytes */{taille}'
            return r
    longueur = fin - debut + 1
    morceau = db.session.query(db.func.substr(Video.donnees, debut + 1, longueur)).filter(Video.id == video_id).scalar()
    r = Response(bytes(morceau or b''), status=206 if partiel else 200, mimetype=mime)
    r.headers['Accept-Ranges'] = 'bytes'
    r.headers['Content-Length'] = str(longueur)
    if partiel:
        r.headers['Content-Range'] = f'bytes {debut}-{fin}/{taille}'
    r.headers['Cache-Control'] = 'public, max-age=31536000, immutable'   # une vidéo n'est jamais modifiée… sauf compression :
    if db.session.query(Video.statut).filter(Video.id == video_id).scalar() != 'prete':
        r.headers['Cache-Control'] = 'no-store'                          # …alors pas de cache tant qu'elle n'est pas prête
    return r
