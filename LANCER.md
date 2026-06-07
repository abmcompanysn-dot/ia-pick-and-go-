# Guide de démarrage — JEL DEM / DALL JAMM

## ÉTAPE 1 — Installer Python (une seule fois)

1. Va sur **https://python.org/downloads** → télécharge Python 3.11
2. Lance l'installeur, **cocher "Add Python to PATH"** (important !)
3. Clique "Install Now"

---

## ÉTAPE 2 — Installer toutes les dépendances (une seule fois)

Ouvre un terminal **dans le dossier du projet** (clic droit → "Ouvrir dans le terminal") :

```bash
pip install -r requirements.txt
```

Pour la reconnaissance faciale (optionnel, plus complexe) :
```bash
pip install cmake dlib face_recognition
```

---

## ÉTAPE 3 — Configurer le fichier .env

Crée un fichier `.env` dans le dossier (ou édite l'existant) :

```
GROQ_API_KEY=ta_cle_groq_ici
NGROK_AUTH_TOKEN=ton_token_ngrok_ici
```

- Groq gratuit : https://console.groq.com
- Ngrok gratuit : https://dashboard.ngrok.com

---

## ÉTAPE 4 — Générer les certificats SSL (une seule fois)

```bash
python generate_certs.py
```

Crée `key.pem` et `cert.pem` dans le dossier.

---

## ÉTAPE 5 — Lancer le serveur principal

```bash
python main.py
```

Le serveur démarre et affiche :
```
 LE SERVEUR DALL JAMM EST EN LIGNE (SSL ACTIF)
 Lien local    : https://192.168.x.x:8000
 Admin         : https://192.168.x.x:8000/admin
```

**Ouvrir dans le navigateur** → accepter l'alerte de sécurité SSL (cliquer "Paramètres avancés" → "Continuer").

---

## ÉTAPE 6 — Lecteur RFID Windows USB (dans un 2ème terminal)

Branche ton lecteur RFID USB. Dans un **deuxième terminal** :

```bash
python rfid_windows.py
```

Passe une carte devant le lecteur → JEL DEM identifie le client automatiquement.

---

## ÉTAPE 7 — Ajouter des produits à reconnaître

### Méthode rapide (photo → base de données) :

1. Prends une ou plusieurs photos du produit (différents angles)
2. Place les photos dans le dossier `produits_dataset/`
   - Nommage : `NomProduit_front.jpg`, `NomProduit_back.jpg`, etc.
3. L'index se recharge automatiquement au démarrage du serveur

### Ajouter le prix via l'interface Manager :
- Va sur `https://IP:8000/manager`
- Remplis le formulaire Nom + Prix en FCFA → Ajouter

---

## ÉTAPE 8 — Entraîner le modèle IA sur vos produits (optionnel)

Si tu veux que la détection YOLO reconnaisse tes produits spécifiques :

```bash
python train_model.py
```

Le modèle s'entraîne et crée `runs/detect/hyflex_training/.../best.pt`.
Ensuite remplace `best.pt` à la racine par ce nouveau modèle.

---

## RÉSUMÉ — Ordre de lancement quotidien

```
Terminal 1 :  python main.py         (serveur principal)
Terminal 2 :  python rfid_windows.py (lecteur badge USB, si besoin)
Navigateur :  https://VOTRE_IP:8000
```

---

## Dépannage courant

| Problème | Solution |
|---|---|
| `pip` non reconnu | Python pas installé ou pas dans PATH |
| Erreur SSL navigateur | Normal — cliquer "Paramètres avancés" → "Continuer" |
| Caméra non détectée | Vérifier qu'OpenCV voit la webcam avec `python -c "import cv2; print(cv2.VideoCapture(0).isOpened())"` |
| RFID pas détecté | Vérifier que `rfid_windows.py` est lancé et que le lecteur est branché |
| Google Sheets lent | Normal, les synchros se font en arrière-plan |
