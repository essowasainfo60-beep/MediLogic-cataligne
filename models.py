import secrets
from urllib.parse import quote

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def nouveau_code_lien():
    return secrets.token_urlsafe(9)  # 12 caractères aléatoires

class Boutique(UserMixin, db.Model):
    __tablename__ = 'boutiques'

    id = db.Column(db.Integer, primary_key=True)
    nom_boutique = db.Column(db.String(100), nullable=False)
    proprietaire_nom = db.Column(db.String(50), nullable=False)
    proprietaire_prenom = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    mot_de_passe_hash = db.Column(db.String(200), nullable=False)
    question_secrete = db.Column(db.String(200), nullable=False)
    reponse_secrete_hash = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, default=False)
    logo_url = db.Column(db.String(500), nullable=True)
    whatsapp = db.Column(db.String(50), nullable=True)  # Numéro WhatsApp de la boutique
    description = db.Column(db.Text, nullable=True)       # présentation affichée aux clients
    adresse = db.Column(db.String(255), nullable=True)    # où se trouve la boutique
    # Frais de livraison : 'livreur_garde' (il garde ses frais et ne remet que les articles)
    # ou 'boutique_collecte' (il remet tout, la boutique le paie ensuite). Voir caisse.py.
    mode_frais = db.Column(db.String(20), nullable=False, default='livreur_garde', server_default='livreur_garde')
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)
    # Code secret du lien envoyé aux clients (/c/<code>) : impossible à deviner,
    # contrairement à /boutique/1, /boutique/2… Régénérable pour couper l'ancien lien.
    lien_public = db.Column(db.String(32), unique=True, index=True, default=lambda: nouveau_code_lien())

    def set_mot_de_passe(self, mot_de_passe):
        self.mot_de_passe_hash = generate_password_hash(mot_de_passe)

    def verifier_mot_de_passe(self, mot_de_passe):
        return check_password_hash(self.mot_de_passe_hash, mot_de_passe)

    def set_reponse_secrete(self, reponse):
        self.reponse_secrete_hash = generate_password_hash(reponse.lower().strip())

    def verifier_reponse_secrete(self, reponse):
        return check_password_hash(self.reponse_secrete_hash, reponse.lower().strip())

    @property
    def lien_carte(self):
        return f'https://www.google.com/maps/search/?api=1&query={quote(self.adresse)}' if self.adresse else None

    est_vendeur = False
    role = 'gerant'
    role_libelle = 'Gérant·e'

    @property
    def nom_utilisateur(self):
        return f'{self.proprietaire_prenom} {self.proprietaire_nom} (gérant)'

    def get_id(self):
        return str(self.id)

class Vendeur(UserMixin, db.Model):
    __tablename__ = 'vendeurs'

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False)
    nom = db.Column(db.String(50), nullable=False)
    prenom = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    mot_de_passe_hash = db.Column(db.String(200), nullable=False)
    actif = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(20), nullable=False, default='vendeur', server_default='vendeur')

    boutique = db.relationship('Boutique', backref=db.backref('vendeurs', cascade='all, delete-orphan'))

    ROLES = {
        'vendeur': ('Vendeur', 'Commandes, clients, impression'),
        'caissier': ('Caissier', 'Comme vendeur + la caisse'),
        'gestionnaire': ('Gestionnaire', 'Tout sauf le compte du gérant'),
    }

    @property
    def role_libelle(self):
        return self.ROLES.get(self.role, (self.role, ''))[0]

    def set_mot_de_passe(self, mot_de_passe):
        self.mot_de_passe_hash = generate_password_hash(mot_de_passe)

    def verifier_mot_de_passe(self, mot_de_passe):
        return check_password_hash(self.mot_de_passe_hash, mot_de_passe)

    def get_id(self):
        return f"vendeur_{self.id}"


class EspaceVendeur(UserMixin):
    """Utilisateur connecté en tant que vendeur : il travaille sur les données de
    SA boutique (current_user.id = id de la boutique), avec un rôle limité
    (voir boutique_routes.PERMISSIONS)."""
    est_vendeur = True

    def __init__(self, vendeur):
        self.vendeur = vendeur

    def __getattr__(self, nom):          # tout le reste vient de la boutique
        return getattr(self.vendeur.boutique, nom)

    def get_id(self):
        return f'vendeur_{self.vendeur.id}'

    @property
    def id(self):
        return self.vendeur.boutique_id

    @property
    def role(self):
        return self.vendeur.role

    @property
    def role_libelle(self):
        return self.vendeur.role_libelle

    @property
    def proprietaire_prenom(self):
        return self.vendeur.prenom

    @property
    def proprietaire_nom(self):
        return self.vendeur.nom

    @property
    def email(self):
        return self.vendeur.email

    @property
    def nom_utilisateur(self):
        return f'{self.vendeur.prenom} {self.vendeur.nom} ({self.vendeur.role_libelle.lower()})'

    def verifier_mot_de_passe(self, mot_de_passe):
        return self.vendeur.verifier_mot_de_passe(mot_de_passe)

    def set_mot_de_passe(self, mot_de_passe):
        self.vendeur.set_mot_de_passe(mot_de_passe)

class Article(db.Model):
    __tablename__ = 'articles'

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    prix = db.Column(db.Float, nullable=False)
    photos_urls = db.Column(db.JSON, default=list)
    stock = db.Column(db.Integer, nullable=True)  # None = stock non suivi pour cet article
    numero = db.Column(db.Integer, nullable=True)  # n° propre à la boutique : 1, 2, 3…
    # Choix proposés au client, ex. {"Taille": ["S", "M", "L"], "Couleur": ["Rouge", "Bleu"]}
    options = db.Column(db.JSON, nullable=True)

    def lire_choix(self, choisis):
        """Valide les choix du client ({option: valeur}) ; renvoie le texte « Taille M, Rouge » ou lève ValueError."""
        morceaux = []
        for option, valeurs in (self.options or {}).items():
            valeur = (choisis.get(option) or '').strip()
            if valeur not in valeurs:
                raise ValueError(f'Choisissez : {option.lower()}')
            morceaux.append(f'{option} {valeur}' if option.lower().startswith('taille') or option.lower().startswith('pointure') else valeur)
        return ', '.join(morceaux)

    @staticmethod
    def prochain_numero(boutique_id):
        dernier = db.session.query(db.func.max(Article.numero)).filter(Article.boutique_id == boutique_id).scalar()
        return (dernier or 0) + 1
    archive = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    boutique = db.relationship('Boutique', backref=db.backref('articles', cascade='all, delete-orphan'))

class Commande(db.Model):
    __tablename__ = 'commandes'

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False)
    client_nom = db.Column(db.String(100), nullable=False)
    client_telephone = db.Column(db.String(50), nullable=False)
    client_adresse = db.Column(db.Text, nullable=False)
    instructions = db.Column(db.Text, nullable=True)
    articles_json = db.Column(db.JSON, nullable=False)
    total = db.Column(db.Float, nullable=False)
    numero_commande = db.Column(db.Integer, nullable=True)
    statut = db.Column(db.String(20), nullable=False, default='nouvelle', server_default='nouvelle')
    date_commande = db.Column(db.DateTime, default=datetime.utcnow)
    lu = db.Column(db.Boolean, default=False)
    # Position GPS partagée par le client au moment de commander (facultatif)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    # Livraison
    livreur_id = db.Column(db.Integer, db.ForeignKey('livreurs.id'), nullable=True)
    code_livraison = db.Column(db.String(32), unique=True, nullable=True)  # lien secret du livreur
    date_livraison = db.Column(db.DateTime, nullable=True)
    # D'où vient la commande : catalogue en ligne, ou saisie par la boutique (live TikTok…)
    source = db.Column(db.String(30), nullable=False, default='catalogue', server_default='catalogue')
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id'), nullable=True)
    stock_deduit = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    # total = sous-total des articles + frais de livraison (montant à encaisser)
    frais_livraison = db.Column(db.Float, nullable=False, default=0, server_default='0')
    # Caisse : l'argent de la commande a-t-il été remis à la boutique ? Les frais payés au livreur ?
    reglee = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    date_reglement = db.Column(db.DateTime, nullable=True)
    frais_payes = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    # Lien de suivi envoyé au client (/suivi/<code>)
    code_suivi = db.Column(db.String(32), unique=True, index=True, default=lambda: nouveau_code_lien())
    # Livraison ratée (client absent, injoignable…) : motif noté par le livreur
    motif_echec = db.Column(db.String(200), nullable=True)
    date_echec = db.Column(db.DateTime, nullable=True)
    tentatives = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    # Photo prise par le livreur à la remise (preuve de livraison)
    photo_preuve = db.Column(db.String(300), nullable=True)
    date_depart = db.Column(db.DateTime, nullable=True)   # remise au livreur (dernière tentative)
    date_arrivee = db.Column(db.DateTime, nullable=True)  # le livreur a signalé « Je suis arrivé »
    # Moment de livraison souhaité par le client (« Demain 05/11 · Soir (16h-20h) »)
    creneau = db.Column(db.String(80), nullable=True)
    # Qui a fait quoi (gérant ou vendeur)
    saisie_par = db.Column(db.String(120), nullable=True)
    confirmee_par = db.Column(db.String(120), nullable=True)
    # Code promo : réduction sur les articles (total = articles - remise + livraison)
    code_promo = db.Column(db.String(30), nullable=True)
    remise = db.Column(db.Float, nullable=False, default=0, server_default='0')

    boutique = db.relationship('Boutique', backref=db.backref('commandes', cascade='all, delete-orphan'))
    livreur = db.relationship('Livreur', backref='commandes')
    zone = db.relationship('Zone', backref='commandes')

    STATUTS = {
        'nouvelle': ('Nouvelle', 'bg-blue-100 text-blue-800'),
        'confirmee': ('Confirmée · à livrer', 'bg-yellow-100 text-yellow-800'),
        'en_livraison': ('En livraison', 'bg-purple-100 text-purple-800'),
        'echec': ('Échec · à relancer', 'bg-red-100 text-red-800'),
        'livree': ('Livrée', 'bg-green-100 text-green-800'),
        'retournee': ('Retournée', 'bg-orange-100 text-orange-800'),
        'annulee': ('Annulée', 'bg-red-100 text-red-800'),
    }

    MOTIFS_ECHEC = ['Client injoignable', 'Client absent', 'Refus du client', 'Adresse introuvable',
                    'Reporté à la demande du client', 'Problème de paiement', 'Autre']

    SOURCES = {
        'catalogue': 'Catalogue en ligne',
        'tiktok': 'Live TikTok',
        'facebook': 'Facebook',
        'instagram': 'Instagram',
        'whatsapp': 'WhatsApp',
        'telephone': 'Appel téléphonique',
        'boutique': 'En boutique',
        'autre': 'Autre',
    }

    @property
    def source_libelle(self):
        return self.SOURCES.get(self.source, self.source)

    @staticmethod
    def prochain_numero(boutique_id):
        """Numéro propre à la boutique : 1, 2, 3… (max + 1, sûr même après suppression)."""
        dernier = db.session.query(db.func.max(Commande.numero_commande)).filter(
            Commande.boutique_id == boutique_id).scalar()
        return (dernier or 0) + 1

    @property
    def zone_suggeree(self):
        """Zone que l'adresse désigne, si elle diffère de la zone enregistrée (sinon None)."""
        from zones_detection import zone_pour_adresse
        zones = [z for z in self.boutique.zones if z.active]
        trouvee, _ = zone_pour_adresse(self.client_adresse, zones)
        return trouvee if trouvee and trouvee.id != self.zone_id else None

    @property
    def sous_total(self):
        return sum(a['prix'] * a['quantite'] for a in self.articles_json)

    @property
    def net_articles(self):
        """Ce que rapportent les articles à la boutique, après la remise."""
        return self.sous_total - (self.remise or 0)

    def recalculer_total(self):
        self.total = self.net_articles + (self.frais_livraison or 0)

    @property
    def numero(self):
        return self.numero_commande

    @property
    def lien_carte(self):
        """Itinéraire Google Maps vers le client (position GPS sinon adresse)."""
        if self.latitude is not None and self.longitude is not None:
            destination = f"{self.latitude},{self.longitude}"
        else:
            destination = quote(self.client_adresse or '')
        return f"https://www.google.com/maps/dir/?api=1&destination={destination}"

    @property
    def carte_integree(self):
        """Carte OpenStreetMap à intégrer (seulement si la position GPS est connue)."""
        if self.latitude is None or self.longitude is None:
            return None
        lat, lon, d = self.latitude, self.longitude, 0.004
        return (f"https://www.openstreetmap.org/export/embed.html?bbox={lon-d},{lat-d},{lon+d},{lat+d}"
                f"&layer=mapnik&marker={lat},{lon}")

    @property
    def statut_libelle(self):
        return self.STATUTS.get(self.statut, (self.statut, ''))[0]

    @property
    def statut_classe(self):
        return self.STATUTS.get(self.statut, ('', 'bg-gray-100 text-gray-800'))[1]


def enregistrer_avec_numero(objet, champ, prochain, essais=5):
    """Ajoute `objet` avec le prochain numéro de sa boutique. Si deux enregistrements
    simultanés prennent le même numéro, l'index unique refuse le second : on réessaie."""
    from sqlalchemy.exc import IntegrityError
    for essai in range(essais):
        with db.session.no_autoflush:
            setattr(objet, champ, prochain(objet.boutique_id))
        db.session.add(objet)
        try:
            db.session.commit()
            return objet
        except IntegrityError:
            db.session.rollback()
            if essai == essais - 1:
                raise


class Photo(db.Model):
    """Image (photo d'article ou logo) stockée directement dans la base Neon."""
    __tablename__ = 'photos'

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    donnees = db.Column(db.LargeBinary, nullable=False)
    mime = db.Column(db.String(50), nullable=False, default='image/jpeg')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    boutique = db.relationship('Boutique', backref=db.backref('photos', cascade='all, delete-orphan', lazy='dynamic'))


class CleBiometrique(db.Model):
    """Appareil autorisé à se connecter par Face ID / empreinte / Windows Hello
    (WebAuthn). On ne stocke que la clé publique : la biométrie reste sur l'appareil."""
    __tablename__ = 'cles_biometriques'

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    credential_id = db.Column(db.String(400), unique=True, nullable=False)
    cle_publique = db.Column(db.LargeBinary, nullable=False)
    compteur = db.Column(db.Integer, default=0)
    libelle = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    derniere_utilisation = db.Column(db.DateTime)

    boutique = db.relationship('Boutique', backref=db.backref('cles_biometriques', cascade='all, delete-orphan'))


class Livreur(db.Model):
    """Livreur d'une boutique. Il n'a pas de compte : il reçoit pour chaque
    course un lien secret (/livraison/<code>) pour voir la carte et valider."""
    __tablename__ = 'livreurs'

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=False)
    telephone = db.Column(db.String(50), nullable=False)
    actif = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Lien secret de l'espace du livreur (/l/<code>), installable sur son téléphone
    code_acces = db.Column(db.String(32), unique=True, index=True, default=lambda: nouveau_code_lien())

    boutique = db.relationship('Boutique', backref=db.backref('livreurs', cascade='all, delete-orphan'))

    @property
    def telephone_whatsapp(self):
        return ''.join(c for c in self.telephone if c.isdigit())


class Zone(db.Model):
    """Zone de livraison (quartiers) confiée de préférence à un livreur :
    à l'attribution d'une commande de cette zone, ce livreur est proposé d'office."""
    __tablename__ = 'zones'

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=False)
    quartiers = db.Column(db.Text)  # quartiers couverts, pour aider le client à choisir
    livreur_id = db.Column(db.Integer, db.ForeignKey('livreurs.id'), nullable=True)
    frais = db.Column(db.Float, nullable=False, default=0, server_default='0')  # frais de livraison de la zone
    active = db.Column(db.Boolean, default=True)

    boutique = db.relationship('Boutique', backref=db.backref('zones', cascade='all, delete-orphan'))
    livreur = db.relationship('Livreur', backref='zones')


class MouvementStock(db.Model):
    """Journal de chaque entrée / sortie de stock : rien ne change sans trace."""
    __tablename__ = 'mouvements_stock'

    TYPES = {
        'entree': 'Entrée (réception)',
        'vente': 'Vente livrée',
        'annulation': 'Annulation de livraison',
        'retour': 'Retour client',
        'inventaire': 'Correction d\'inventaire',
    }

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    article_id = db.Column(db.Integer, db.ForeignKey('articles.id'), nullable=False, index=True)
    commande_id = db.Column(db.Integer, db.ForeignKey('commandes.id'), nullable=True)
    type = db.Column(db.String(20), nullable=False)
    quantite = db.Column(db.Integer, nullable=False)  # + entrée, - sortie
    stock_apres = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255))
    date = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    boutique = db.relationship('Boutique', backref=db.backref('mouvements_stock', cascade='all, delete-orphan', lazy='dynamic'))
    article = db.relationship('Article', backref=db.backref('mouvements', cascade='all, delete-orphan', lazy='dynamic'))
    commande = db.relationship('Commande', backref='mouvements_stock')

    @property
    def type_libelle(self):
        return self.TYPES.get(self.type, self.type)


class Retour(db.Model):
    """Articles rapportés après livraison : échange ou retour définitif."""
    __tablename__ = 'retours'

    id = db.Column(db.Integer, primary_key=True)
    commande_id = db.Column(db.Integer, db.ForeignKey('commandes.id'), nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False)  # 'echange' ou 'retour'
    motif = db.Column(db.Text)
    lignes = db.Column(db.JSON, nullable=False)  # [{nom, prix, quantite, article_id}]
    montant = db.Column(db.Float, nullable=False, default=0)
    date = db.Column(db.DateTime, default=datetime.utcnow)

    commande = db.relationship('Commande', backref=db.backref('retours', cascade='all, delete-orphan',
                                                              order_by='Retour.date'))

    @property
    def type_libelle(self):
        return 'Échange' if self.type == 'echange' else 'Retour définitif'


class MouvementCaisse(db.Model):
    """Entrée (+) ou sortie (−) d'argent de la caisse de la boutique. Le solde est la somme."""
    __tablename__ = 'mouvements_caisse'

    TYPES = {
        'versement': ('Versement livreur', 'bg-green-100 text-green-800'),
        'vente_directe': ('Vente en boutique', 'bg-green-100 text-green-800'),
        'apport': ('Apport', 'bg-blue-100 text-blue-800'),
        'charge': ('Charge', 'bg-red-100 text-red-800'),
        'paiement_livreur': ('Paiement livreur', 'bg-purple-100 text-purple-800'),
        'remboursement': ('Remboursement client', 'bg-orange-100 text-orange-800'),
        'retrait': ('Retrait', 'bg-gray-100 text-gray-800'),
        'correction': ('Correction', 'bg-gray-100 text-gray-800'),
    }
    CATEGORIES = ['Achat de marchandises', 'Loyer', 'Électricité / eau', 'Internet / téléphone', 'Transport',
                  'Salaires', 'Publicité', 'Emballage', 'Impôts / taxes', 'Divers']

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    type = db.Column(db.String(20), nullable=False)
    categorie = db.Column(db.String(50))
    libelle = db.Column(db.String(200))
    montant = db.Column(db.Float, nullable=False)
    livreur_id = db.Column(db.Integer, db.ForeignKey('livreurs.id'), nullable=True)
    commande_id = db.Column(db.Integer, db.ForeignKey('commandes.id'), nullable=True)
    par = db.Column(db.String(120), nullable=True)   # qui a enregistré le mouvement

    boutique = db.relationship('Boutique', backref=db.backref('mouvements_caisse', cascade='all, delete-orphan', lazy='dynamic'))
    livreur = db.relationship('Livreur')
    commande = db.relationship('Commande')

    @property
    def type_libelle(self):
        return self.TYPES.get(self.type, (self.type, ''))[0]

    @property
    def type_classe(self):
        return self.TYPES.get(self.type, ('', 'bg-gray-100 text-gray-800'))[1]


class CodePromo(db.Model):
    """Code de réduction (ex. LIVE10 pour un live TikTok)."""
    __tablename__ = 'codes_promo'
    __table_args__ = (db.UniqueConstraint('boutique_id', 'code', name='uq_code_promo_boutique'),)

    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False, index=True)
    code = db.Column(db.String(30), nullable=False)
    type = db.Column(db.String(15), nullable=False, default='pourcentage')   # 'pourcentage' ou 'montant'
    valeur = db.Column(db.Float, nullable=False)
    minimum = db.Column(db.Float, nullable=True)            # achat minimum en FCFA (articles)
    min_articles = db.Column(db.Integer, nullable=True)     # nombre minimum d'articles dans la commande
    date_fin = db.Column(db.Date, nullable=True)
    utilisations_max = db.Column(db.Integer, nullable=True)
    utilisations = db.Column(db.Integer, nullable=False, default=0)
    affiche = db.Column(db.Boolean, nullable=False, default=False)   # annoncé en haut du catalogue
    actif = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    boutique = db.relationship('Boutique', backref=db.backref('codes_promo', cascade='all, delete-orphan'))

    @property
    def libelle(self):
        if self.type == 'pourcentage':
            return f"-{self.valeur:g} %"
        return f"-{self.valeur:,.0f} FCFA".replace(',', ' ')

    @property
    def conditions(self):
        """Ex. « dès 2 articles et 10 000 FCFA d'achat »."""
        morceaux = []
        if self.min_articles and self.min_articles > 1:
            morceaux.append(f"{self.min_articles} articles")
        if self.minimum:
            morceaux.append(f"{self.minimum:,.0f} FCFA d'achat".replace(',', ' '))
        return ('dès ' + ' et '.join(morceaux)) if morceaux else ''



class AbonnementPush(db.Model):
    """Téléphone d'un client qui a accepté d'être prévenu (notification qui sonne)
    pour une commande : « Votre livreur est arrivé »."""
    __tablename__ = 'abonnements_push'

    id = db.Column(db.Integer, primary_key=True)
    commande_id = db.Column(db.Integer, db.ForeignKey('commandes.id'), nullable=False, index=True)
    endpoint = db.Column(db.String(1000), nullable=False)
    cle_p256dh = db.Column(db.String(200), nullable=False)
    cle_auth = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    commande = db.relationship('Commande', backref=db.backref('abonnements_push', cascade='all, delete-orphan'))


class Parametre(db.Model):
    """Réglages techniques de l'application (ex. clés des notifications)."""
    __tablename__ = 'parametres'

    cle = db.Column(db.String(50), primary_key=True)
    valeur = db.Column(db.Text, nullable=False)
