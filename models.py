from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

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
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)


    
    def set_mot_de_passe(self, mot_de_passe):
        self.mot_de_passe_hash = generate_password_hash(mot_de_passe)
    
    def verifier_mot_de_passe(self, mot_de_passe):
        return check_password_hash(self.mot_de_passe_hash, mot_de_passe)
    
    def set_reponse_secrete(self, reponse):
        self.reponse_secrete_hash = generate_password_hash(reponse.lower().strip())
    
    def verifier_reponse_secrete(self, reponse):
        return check_password_hash(self.reponse_secrete_hash, reponse.lower().strip())
    
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
    
    boutique = db.relationship('Boutique', backref='vendeurs')
    
    def set_mot_de_passe(self, mot_de_passe):
        self.mot_de_passe_hash = generate_password_hash(mot_de_passe)
    
    def verifier_mot_de_passe(self, mot_de_passe):
        return check_password_hash(self.mot_de_passe_hash, mot_de_passe)
    
    def get_id(self):
        return f"vendeur_{self.id}"

class Article(db.Model):
    __tablename__ = 'articles'
    
    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    prix = db.Column(db.Float, nullable=False)
    photos_urls = db.Column(db.JSON, default=list)
    archive = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    boutique = db.relationship('Boutique', backref='articles')

class Commande(db.Model):
    __tablename__ = 'commandes'
    
    id = db.Column(db.Integer, primary_key=True)
    boutique_id = db.Column(db.Integer, db.ForeignKey('boutiques.id'), nullable=False)
    client_nom = db.Column(db.String(100), nullable=False)
    client_telephone = db.Column(db.String(50), nullable=False)
    client_adresse = db.Column(db.Text, nullable=False)
    instructions = db.Column(db.Text, nullable=True)  # ← AJOUTE CETTE LIGNE
    articles_json = db.Column(db.JSON, nullable=False)
    total = db.Column(db.Float, nullable=False)
    numero_commande = db.Column(db.Integer, nullable=True)  # ← Ajoute cette ligne
    date_commande = db.Column(db.DateTime, default=datetime.utcnow)
    lu = db.Column(db.Boolean, default=False)
    
    boutique = db.relationship('Boutique', backref='commandes')