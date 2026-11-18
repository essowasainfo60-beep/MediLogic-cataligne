"""Lecture d'un SMS Mixx by Yas / Moov Money (Flooz) collé ou partagé : opérateur, opération, montant,
numéro et référence de la transaction.

Les opérateurs ne publient pas le texte exact de leurs SMS : la lecture cherche les formes courantes
(« Ref : … », « ID : … », « Txn ID … », « Référence … », montants en F / FCFA, numéros togolais) et
laisse toujours le vendeur vérifier avant de valider."""
import re

_OPERATEURS = [('flooz', re.compile(r'moov|flooz', re.I)),
               ('mixx', re.compile(r'mixx|\byas\b|t-?money|togocom', re.I))]
_TYPES = [('retrait', re.compile(r'retrait|cash[ -]?out|retir', re.I)),
          ('depot', re.compile(r'd[ée]p[oô]t|cash[ -]?in|rechargement de votre compte|cr[ée]dit[ée] de', re.I)),
          ('transfert', re.compile(r'transf[ée]r|envoy[ée]|envoi\b', re.I))]
_REF_ETIQUETTE = re.compile(
    r'(?:r[ée]f(?:[ée]rence)?|n[°o]\s*(?:de\s*)?(?:transaction|op[ée]ration)|id\s*(?:de\s*)?(?:transaction|trans|txn)?'
    r'|txn\s*id|trans(?:action)?\s*id)\s*[:#=\-]?\s*([A-Za-z0-9][A-Za-z0-9.\-_/]{3,40})', re.I)
_JETON = re.compile(r'\b(?=[A-Za-z0-9.\-_/]*\d)(?=[A-Za-z0-9.\-_/]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9.\-_/]{7,40}\b')
_MONTANT = re.compile(r'(\d{1,3}(?:[ .  ]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*(?:F\s?CFA|FCFA|XOF|F)\b', re.I)
_TEL = re.compile(r'(?<!\d)(?:\+?228[ .]?)?([79]\d(?:[ .]?\d{2}){3})(?!\d)')
_A_EVITER = re.compile(r'(solde|frais|commission|taxe|nouveau solde)\W{0,3}[^\d]{0,15}$', re.I)


def lire_sms(texte):
    """Renvoie {'operateur', 'type', 'montant', 'telephone', 'sms_ref'} (chaque valeur peut être None)."""
    texte = (texte or '').strip()[:2000]
    res = {'operateur': None, 'type': None, 'montant': None, 'telephone': None, 'sms_ref': None}
    if not texte:
        return res
    for code, motif in _OPERATEURS:
        if motif.search(texte):
            res['operateur'] = code
            break
    for code, motif in _TYPES:
        if motif.search(texte):
            res['type'] = code
            break
    # Référence : d'abord après une étiquette (Ref, ID, Txn…), sinon un long jeton lettres + chiffres
    for m in _REF_ETIQUETTE.finditer(texte):
        val = m.group(1).strip('.-_/')
        if any(c.isdigit() for c in val) and len(val) >= 4:
            res['sms_ref'] = val.upper()
            break
    if not res['sms_ref']:
        jetons = [j for j in _JETON.findall(texte) if not re.fullmatch(r'\+?\d[\d .]*', j)]
        if jetons:
            res['sms_ref'] = max(jetons, key=len).upper()
    # Montant : le premier qui n'est pas un solde ni des frais
    for m in _MONTANT.finditer(texte):
        if _A_EVITER.search(texte[max(0, m.start() - 30):m.start()]):
            continue
        chiffres = re.sub(r'\D', '', m.group(1))
        if chiffres and 0 < int(chiffres) <= 5000000:
            res['montant'] = int(chiffres)
            break
    # Numéro togolais (8 chiffres, commençant par 7 ou 9), hors référence
    for m in _TEL.finditer(texte):
        numero = re.sub(r'\D', '', m.group(1))
        if res['sms_ref'] and numero in re.sub(r'\D', '', res['sms_ref']):
            continue
        res['telephone'] = numero
        break
    return res
