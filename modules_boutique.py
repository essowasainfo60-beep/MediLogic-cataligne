"""Modules activables boutique par boutique (par la boutique gestionnaire ou l'administrateur).

Une boutique peut, par exemple, ne prendre que « Mixx & Flooz » : les autres modules sont alors cachés
et fermés (liens masqués, pages refusées, catalogue public indisponible). Boutique.modules vaut None
pour une boutique qui n'a jamais été réglée : tout est ouvert (comme avant). Les modules « Vente au
comptoir » et « Mixx & Flooz » demandent en plus une formule qui les inclut (voir abonnement.py)."""
from collections import OrderedDict

MODULES = OrderedDict([
    ('catalogue', ('Catalogue en ligne', 'Lien du catalogue, promos, nouveautés, demandes des clients', {
        'partager', 'codes_promo', 'modifier_code_promo', 'regler_fidelite', 'demandes_clients', 'prevenir_demande',
        'classer_demande', 'annoncer_article', 'annoncer_nouveautes', 'basculer_en_ligne', 'message_statut',
        'regenerer_lien'})),
    ('commandes', ('Commandes et livraisons', 'Commandes, livreurs, zones, suivi des livraisons', {
        'commandes', 'commande_details', 'nouvelle_commande', 'valider_commande_boutique', 'proposer_aux_livreurs',
        'changer_mode_reception', 'attribuer_livreur', 'imprimer_commande', 'changer_mode_frais', 'versement_commande',
        'payer_frais_commande', 'bon_course', 'livreurs', 'modifier_livreur', 'basculer_livreur', 'changer_statut_commande',
        'envoyer_confirmation_client', 'ajouter_zone', 'modifier_zone', 'zones_modele', 'envoyer_espace_livreur',
        'nouveau_lien_livreur', 'caisse_versement', 'caisse_paiement_livreur', 'api_livreurs_en_route',
        'api_trajet_commande', 'discussion_livreur_prive', 'discussion_commande_boutique', 'livraisons',
        'changer_frais_commande', 'changer_zone_commande'})),
    ('comptoir', ('Vente au comptoir', 'Caisse, tickets, codes-barres, créances, approvisionnement', {
        'vendre', 'vendre_valider', 'ticket_vente', 'ventes_jour', 'annuler_vente', 'code_barre_nouveau', 'page_creances',
        'payer_creance', 'valider_paiement_creance', 'refuser_paiement_creance', 'validations', 'demander_charge',
        'demander_annulation', 'traiter_demande_gerant', 'etiquettes', 'etiquettes_codes', 'approvisionnement',
        'approvisionner', 'payer_approvisionnement'})),
    ('momo', ('Mixx & Flooz', 'Dépôts, retraits et transferts mobile money du kiosque', {
        'momo_accueil', 'momo_operateur', 'momo_operation', 'momo_detail', 'momo_photo', 'momo_annuler', 'momo_caisses',
        'momo_point', 'momo_reglages', 'momo_journal_csv', 'momo_historique', 'momo_recu', 'momo_lire_sms', 'momo_partage'})),
])
# Articles et stock : ouverts dès qu'un module qui vend des articles est actif
ARTICLES = {'articles', 'articles_archives', 'ajouter_article', 'modifier_article', 'archiver_article', 'restaurer_article',
            'supprimer_photo', 'photo_principale', 'envoyer_video', 'inventaire', 'entree_stock', 'mouvements_stock',
            'synchro_page', 'synchro_cle'}
VENDENT_ARTICLES = {'catalogue', 'commandes', 'comptoir'}
# Page d'arrivée selon les modules actifs (accueil d'une boutique qui ne fait pas de commandes)
ACCUEILS = [('commandes', 'boutique.dashboard'), ('comptoir', 'boutique.vendre'), ('momo', 'boutique.momo_accueil'),
            ('catalogue', 'boutique.articles')]


def actifs(boutique):
    import abonnement
    if boutique is None or boutique.modules is None or abonnement.est_gestionnaire(boutique):
        return set(MODULES)
    return {code for code in MODULES if (boutique.modules or {}).get(code)}


def module_de(nom_page):
    for code, (_, _, pages) in MODULES.items():
        if nom_page in pages:
            return code
    return 'articles' if nom_page in ARTICLES else None


def autorise(boutique, nom_page):
    m = module_de(nom_page)
    if m is None:
        return True
    a = actifs(boutique)
    return bool(a & VENDENT_ARTICLES) if m == 'articles' else m in a


def page_accueil(boutique):
    """Endpoint d'arrivée : le tableau de bord, sauf pour une boutique sans commandes (ex. Mixx & Flooz seul)."""
    a = actifs(boutique)
    for code, endpoint in ACCUEILS:
        if code in a:
            return endpoint
    return 'boutique.dashboard'


def regler(boutique, codes):
    from models import db
    boutique.modules = {code: code in codes for code in MODULES}
    db.session.commit()
