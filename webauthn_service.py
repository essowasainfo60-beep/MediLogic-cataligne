"""
Connexion par biométrie de l'appareil (Face ID / empreinte / Windows Hello),
via WebAuthn : même principe que dans GBoutik-MediLogic et GHP, avec un
stockage SQLAlchemy (table cles_biometriques).

Deux étapes :
  - Inscription : une boutique déjà connectée autorise CET appareil
    (options_inscription puis verifier_inscription).
  - Connexion, à la place du mot de passe : clé « résidente », donc pas besoin
    de taper l'email ; l'appareil propose ses clés et la boutique est retrouvée
    grâce au credential_id (options_connexion puis verifier_connexion).

WebAuthn ne fonctionne qu'en HTTPS (ou sur localhost).
"""

import base64
import json
from datetime import datetime

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from models import db, CleBiometrique

RP_NAME = "CTL Catalogue"


def _rp_id_et_origin(request):
    rp_id = request.host.split(':')[0]
    est_local = rp_id in ('localhost', '127.0.0.1', '::1')
    scheme = request.scheme if est_local else 'https'
    return rp_id, f"{scheme}://{request.host}"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode('ascii'))


def options_inscription(request, boutique):
    rp_id, _ = _rp_id_et_origin(request)
    deja = [PublicKeyCredentialDescriptor(id=_unb64(c.credential_id)) for c in boutique.cles_biometriques]
    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=f"boutique:{boutique.id}".encode(),
        user_name=boutique.email,
        user_display_name=boutique.nom_boutique,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Capteur intégré de l'appareil (pas de clé USB externe)
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            # Clé découvrable : la page de connexion la propose sans email
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=deja,
    )
    return webauthn.options_to_json(options), _b64(options.challenge)


def verifier_inscription(request, boutique, credential, challenge_b64, libelle=None):
    rp_id, origin = _rp_id_et_origin(request)
    verification = webauthn.verify_registration_response(
        credential=credential,
        expected_challenge=_unb64(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        require_user_verification=True,
    )
    db.session.add(CleBiometrique(
        boutique_id=boutique.id,
        credential_id=_b64(verification.credential_id),
        cle_publique=verification.credential_public_key,
        compteur=verification.sign_count,
        libelle=(libelle or 'Appareil')[:150],
    ))
    db.session.commit()


def options_connexion(request):
    """Sans allow_credentials : le navigateur retrouve seul les clés de cet
    appareil pour ce site (Face ID / empreinte affiche son sélecteur)."""
    rp_id, _ = _rp_id_et_origin(request)
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return webauthn.options_to_json(options), _b64(options.challenge)


def verifier_connexion(request, credential, challenge_b64):
    """Vérifie la signature de l'appareil et retourne la boutique.
    Lève ValueError avec un message lisible en cas d'échec."""
    rp_id, origin = _rp_id_et_origin(request)
    cred = json.loads(credential) if isinstance(credential, str) else credential
    cred_id = cred.get('id') or cred.get('rawId')
    if not cred_id:
        raise ValueError("Réponse de l'appareil incomplète.")

    cle = CleBiometrique.query.filter_by(credential_id=_b64(webauthn.base64url_to_bytes(cred_id))).first()
    if not cle:
        raise ValueError("Cet appareil n'est associé à aucune boutique (ou a été retiré).")

    verification = webauthn.verify_authentication_response(
        credential=cred,
        expected_challenge=_unb64(challenge_b64),
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=cle.cle_publique,
        credential_current_sign_count=cle.compteur or 0,
        require_user_verification=True,
    )
    cle.compteur = verification.new_sign_count
    cle.derniere_utilisation = datetime.utcnow()
    db.session.commit()
    return cle.boutique
