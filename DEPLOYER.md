# Déploiement Cloud — JEL DEM / DALL JAMM

## Railway (recommandé — plus simple)

### Étape 1 — Compte Railway gratuit
→ Va sur **https://railway.app** → "Start a new project" → connexion avec GitHub

### Étape 2 — Pusher le code sur GitHub

Dans le terminal du dossier projet :

```bash
git add .
git commit -m "Deploiement cloud"
git push
```

> Si pas encore de repo GitHub : va sur https://github.com/new, crée le repo,
> puis suis les instructions affichées pour y pousser ton code local.

### Étape 3 — Créer le projet Railway

1. Sur Railway → **"New Project"** → **"Deploy from GitHub repo"**
2. Sélectionne ton repo `ia-pick-and-go`
3. Railway détecte automatiquement Python et installe les dépendances

### Étape 4 — Ajouter les variables d'environnement

Dans Railway → onglet **"Variables"** → ajouter :

| Clé | Valeur |
|-----|--------|
| `GROQ_API_KEY` | ta clé Groq (https://console.groq.com) |

> `NGROK_AUTH_TOKEN` n'est PAS nécessaire sur Railway (Railway fournit déjà une URL publique).

### Étape 5 — Obtenir l'URL publique

Railway → onglet **"Settings"** → **"Networking"** → **"Generate Domain"**

Tu obtiens une URL comme : `https://jel-dem-xxxxx.railway.app`

C'est l'URL de ton serveur JEL DEM accessible partout dans le monde !

---

## Render (alternative gratuite)

### Étape 1 — Compte Render
→ Va sur **https://render.com** → "Sign Up" avec GitHub

### Étape 2 — Créer le service

1. **"New +"** → **"Web Service"**
2. Connecte ton repo GitHub
3. Paramètres :
   - **Runtime** : Python 3
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `python main.py`

### Étape 3 — Variables d'environnement

Onglet **"Environment"** → ajouter :
- `GROQ_API_KEY` = ta clé Groq

### Étape 4 — Déployer

Clique **"Create Web Service"** → Render build et démarre automatiquement.

---

## Connexion des caméras ESP32 au serveur cloud

Une fois le serveur déployé, mets à jour l'URL dans les firmwares ESP32 :

**Dans `esp32_cam_stream.ino`**, change :
```cpp
// Avant (local)
const char* serverUrl = "wss://192.168.1.x:8000/ws/cam_esp32";

// Après (cloud Railway)
const char* serverUrl = "wss://jel-dem-xxxxx.railway.app/ws/cam_esp32";
```

**Note importante** : sur Railway/Render, pas besoin de `wss://` avec certificat — la plateforme gère le SSL automatiquement.

---

## Connexion du lecteur RFID Windows au serveur cloud

Dans `rfid_windows.py`, change `SERVER_URL` :

```python
# Avant (local)
SERVER_URL = "https://127.0.0.1:8000/api/rfid_login"

# Après (cloud)
SERVER_URL = "https://jel-dem-xxxxx.railway.app/api/rfid_login"
SSL_VERIFY = True  # Railway a un vrai certificat SSL
```

---

## Données persistantes (important !)

Les plateformes cloud gratuites ont un système de fichiers **éphémère** :
`wallets.json` et `transactions_history.json` se réinitialisent à chaque redéploiement.

**Solution** : Ces données sont déjà sauvegardées dans Google Sheets via Apps Script.
→ Le code recharge les données depuis Google au démarrage automatiquement.

---

## Résumé après déploiement

```
Ton serveur tourne 24h/24 sur Railway/Render
URL permanente : https://jel-dem-xxxxx.railway.app

Sur ton PC Windows (si lecteur RFID USB branché) :
  python rfid_windows.py   ← pointe vers l'URL cloud

ESP32-CAM :
  Firmware mis à jour avec l'URL cloud → streaming direct

Google Sheets :
  Synchronisé automatiquement avec le serveur cloud
```
