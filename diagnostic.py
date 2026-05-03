import requests
import json
import sys

def diagnostique_app(url):
    print("="*50)
    print(f"🔍 Diagnostic de : {url}")
    print("="*50)
    
    # 1. Tester la page d'accueil
    print("\n1️⃣ Test de la page d'accueil...")
    try:
        reponse = requests.get(url, timeout=10)
        print(f"   ✅ Statut: {reponse.status_code}")
        if reponse.status_code == 200:
            print("   ✅ Page accessible")
        else:
            print(f"   ❌ Erreur: {reponse.status_code}")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    # 2. Tester la page de connexion
    print("\n2️⃣ Test de la page de connexion...")
    try:
        reponse = requests.get(f"{url}/boutique/connexion", timeout=10)
        print(f"   ✅ Statut: {reponse.status_code}")
        if "connexion" in reponse.text.lower():
            print("   ✅ Formulaire de connexion trouvé")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    # 3. Tenter une connexion avec un faux compte
    print("\n3️⃣ Test de connexion (compte invalide)...")
    try:
        data = {
            'email': 'test@test.com',
            'password': 'faux_mot_de_passe'
        }
        reponse = requests.post(f"{url}/boutique/connexion", data=data, timeout=10)
        print(f"   Statut: {reponse.status_code}")
        if reponse.status_code == 500:
            print("   ❌ Erreur 500 - Problème serveur")
        elif "email ou mot de passe" in reponse.text.lower():
            print("   ✅ Le formulaire traite bien les erreurs")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    print("\n" + "="*50)
    print("✅ Diagnostic terminé")

if __name__ == "__main__":
    url = "https://medilogic-cataligne-1.onrender.com"
    diagnostique_app(url)