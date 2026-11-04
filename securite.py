"""Limite les essais de mot de passe : après 5 échecs en 15 minutes pour un même
compte depuis une même connexion, on bloque 15 minutes (ralentit qui essaie de
deviner un mot de passe). Mémoire du serveur : suffisant avec un seul processus."""
import time

ESSAIS_MAX = 5
FENETRE = 15 * 60
_echecs = {}


def _cle(request, identifiant):
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
    return f"{ip}|{(identifiant or '').strip().lower()}"


def _recents(cle):
    maintenant = time.time()
    liste = [t for t in _echecs.get(cle, []) if maintenant - t < FENETRE]
    _echecs[cle] = liste
    return liste


def bloque(request, identifiant):
    """Minutes d'attente restantes si trop d'échecs, sinon 0."""
    recents = _recents(_cle(request, identifiant))
    if len(recents) < ESSAIS_MAX:
        return 0
    return max(1, int((FENETRE - (time.time() - recents[0])) // 60) + 1)


def echec(request, identifiant):
    _echecs.setdefault(_cle(request, identifiant), []).append(time.time())


def succes(request, identifiant):
    _echecs.pop(_cle(request, identifiant), None)
