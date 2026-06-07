import base64
import os
import json # Pour sauvegarder les données
import csv
import io
import math
import datetime
import cv2 # OpenCV pour les calculs rapides
import mediapipe as mp # Pour la détection des mains
import numpy as np
import requests # Nouvelle importation
import time
from fastapi.middleware.cors import CORSMiddleware
import socket
import asyncio
try:
    import qrcode
except ImportError:
    qrcode = None
try:
    from pyngrok import ngrok
    PYNGROK_AVAILABLE = True
except ImportError:
    PYNGROK_AVAILABLE = False
import pickle # Pour sauvegarder l'index sur le disque
import threading # Pour le multitâche fluide
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, FileResponse
from groq import Groq
from PIL import Image, ImageDraw, ImageFont # Pour dessiner sur les images
from ultralytics import YOLO # Moteur de vision
from pydantic import BaseModel

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# --- CONFIGURATION DU SYSTÈME ---

# --- DÉTECTION DE L'IP LOCALE POUR LES QR CODES ---
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # n'a pas besoin d'être joignable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

LOCAL_IP = get_local_ip()

# 1. URL DE VOTRE API GOOGLE APPS SCRIPT
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxxSOZyptRBlGr0svsXlWzjANkMK8RRz03gVizG56nS6KsIfyVW0ghuyxonCY7ebqYGjQ/exec"

# La base de données des produits sera maintenant gérée dans Google Sheets
# Elle est chargée au démarrage depuis Google Apps Script
DB_PRODUITS = {}

# --- GESTION ASSIGNATION MANUELLE (ALTERNATIVE À LA RECO FACIALE) ---
# Permet à l'admin de dire "C'est Thomas devant la caméra 1"
CAMERA_USER_ASSIGNMENTS = {}

# Cache local UID RFID → nom utilisateur (évite de recontacter Google à chaque scan)
RFID_USER_CACHE = {}

# --- GESTION WALLET (PORTEFEUILLE) ---
WALLET_FILE = "wallets.json"
WALLETS_LOCK = threading.Lock()

def load_wallets():
    if os.path.exists(WALLET_FILE):
        with open(WALLET_FILE, "r") as f:
            return json.load(f)
    return {"Client_Unknown": 5000}

def save_wallets():
    with WALLETS_LOCK:
        with open(WALLET_FILE, "w") as f:
            json.dump(WALLETS, f, indent=4)

WALLETS = load_wallets() # Chargement au démarrage

# Tentative d'import de la reconnaissance faciale
try:
    import face_recognition
    FACE_REC_AVAILABLE = True
except ImportError:
    FACE_REC_AVAILABLE = False
    print("Mode 'Sans Reco Faciale' actif (Module non installe). Utilisez l'assignation manuelle dans l'Admin.")

NGROK_URL = None

# Détection automatique du mode cloud (Railway, Render, etc.)
# Railway injecte RAILWAY_PUBLIC_DOMAIN, Render injecte RENDER_EXTERNAL_URL
def get_cloud_url():
    railway = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway:
        return f"https://{railway}"
    render = os.getenv("RENDER_EXTERNAL_URL")
    if render:
        return render.rstrip("/")
    return None

CLOUD_URL = get_cloud_url()
IS_CLOUD = CLOUD_URL is not None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global NGROK_URL

    public_url = CLOUD_URL  # Priorité à l'URL cloud si disponible

    # Ngrok uniquement en local (pas besoin sur Railway/Render qui ont leur propre URL)
    if not IS_CLOUD:
        auth_token = os.getenv("NGROK_AUTH_TOKEN")
        if PYNGROK_AVAILABLE and auth_token:
            try:
                ngrok.set_auth_token(auth_token)
                tunnel = ngrok.connect(8000, bind_tls=True)
                NGROK_URL = tunnel.public_url
                public_url = NGROK_URL
                print(f"\n" + "═"*60)
                print(f"URL PUBLIQUE NGROK : {NGROK_URL}")
                print(f"Acces mobile : {NGROK_URL}/mobile")
                print("═"*60 + "\n")
            except Exception as e:
                print(f"Erreur Ngrok : {e}")

    if public_url:
        # Synchronisation automatique de l'URL publique avec Google Sheets
        def sync_public_url():
            try:
                requests.post(APPS_SCRIPT_URL, json={
                    "action": "updatePythonUrl",
                    "payload": {"pythonUrl": public_url}
                }, timeout=5)
                print(f"URL publique synchronisee avec Google Sheets : {public_url}")
            except Exception:
                pass
        threading.Thread(target=sync_public_url, daemon=True).start()

    # Lance la boucle d'analyse IA en arrière-plan
    t = threading.Thread(target=background_analysis_loop, daemon=True)
    t.start()
    yield

# --- INITIALISATION UNIQUE DE L'APPLICATION ---
app = FastAPI(lifespan=lifespan)

# --- GESTION DES TRANSACTIONS LOCALES (POUR EXPORT) ---
TRANSACTIONS_FILE = "transactions_history.json"

def save_transaction_local(payload):
    """Sauvegarde une copie locale de la transaction pour l'export CSV."""
    history = []
    if os.path.exists(TRANSACTIONS_FILE):
        with open(TRANSACTIONS_FILE, "r") as f:
            try:
                history = json.load(f)
            except:
                history = []
    
    payload["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history.append(payload)
    with open(TRANSACTIONS_FILE, "w") as f:
        json.dump(history, f, indent=4)

# --- CONFIGURATION CORS (Indispensable pour DALL JAMM) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En production, remplacez par vos domaines Vercel/GitHub
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CHARGEMENT DU MODÈLE YOLO (Le Cerveau) ---
try:
    # Tente de charger votre modèle entraîné, sinon prend le modèle standard
    # On essaie d'utiliser CUDA (GPU) pour une puissance maximale
    if os.path.exists("best.pt"):
        MODEL = YOLO("best.pt")
    else:
        MODEL = YOLO("yolov8n.pt") # Modèle léger par défaut

    # Force le modèle sur GPU si disponible pour la "bonne puissance"
    MODEL.to('cuda') if hasattr(MODEL, 'to') else print("Running on CPU")
    print(f"IA prete. Mode: {'GPU (Puissance Max)' if 'cuda' in str(MODEL.device) else 'CPU (Mode lent)'}")
except Exception as e:
    MODEL = None
    print(f"Erreur chargement YOLO: {e}")

# --- CONFIGURATION MEDIAPIPE (MAINS) ---
try:
    mp_hands = mp.solutions.hands
    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    # On initialise le détecteur de mains (Mode léger pour la vitesse)
    HAND_DETECTOR = mp_hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.3)
    # On initialise le détecteur de corps entier (Pose) pour voir toutes les parties du corps
    POSE_DETECTOR = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, model_complexity=0)
except AttributeError:
    print("\nERREUR CRITIQUE : Vous avez probablement un fichier nomme 'mediapipe.py' dans votre dossier !")
    print("Renommez-le (ex: 'test.py') et relancez. Python essaie de l'importer a la place de la librairie.\n")
    HAND_DETECTOR = None
    POSE_DETECTOR = None
    mp_hands = None
    mp_pose = None
    mp_drawing = None
except Exception as e:
    print(f"MediaPipe non charge : {e}")
    HAND_DETECTOR = None
    POSE_DETECTOR = None
    mp_hands = None
    mp_pose = None
    mp_drawing = None

try:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
except Exception as e:
    print(f"⚠️ Groq non initialisé (GROQ_API_KEY manquante?) : {e}")
    client = None

# --- MÉMOIRE DES CAMÉRAS (POUR LE DASHBOARD ADMIN) ---
# Stocke la dernière image traitée et les infos pour chaque caméra
# Format optimisé pour le streaming fluide
CAMERA_FEEDS = {}
# Structure : 
# { 
#   "cam_id": { 
#       "image_bytes": b'...', "last_seen": "...", "person": "...", 
#       "last_analysis_ts": 0.0, "price": "..." 
#   } 
# }
LATEST_FRAME_BYTES = {} # Stockage brut ultra-rapide pour découpler l'IA

LAST_DETECTIONS = {} # Pour garder les rectangles en mémoire entre deux analyses IA
# --- MÉMOIRE LOGIQUE PICK & GO ---
# Stocke l'état des objets suivis pour détecter les disparitions
# { "cam_id": { track_id: { "class": "coca", "missing_frames": 0, "seen_last": timestamp } } }
# On y stocke aussi maintenant le "vrai nom" identifié par matching visuel
SHELF_STATE = {}

GESTURE_PATHS = {} # {camera_id: {track_id: [(x, y), ...]}}

# --- MÉMOIRE DE TRACKING INDIVIDUEL ---
# Associe un track_id YOLO (personne) à un nom identifié
PERSON_TRACK_MEMORY = {} # {cam_id: {track_id: "Nom"}}
PERSON_ID_ATTEMPTS = {} # Pour ne pas spammer la reco faciale si échec

# --- CHARGEMENT DES VISAGES CONNUS ---
KNOWN_FACE_ENCODINGS = []
KNOWN_FACE_NAMES = []

def load_known_faces():
    """Charge les visages depuis le dossier 'visages'."""
    global KNOWN_FACE_ENCODINGS, KNOWN_FACE_NAMES
    if not FACE_REC_AVAILABLE: return
    
    folder = "visages"
    if not os.path.exists(folder):
        os.makedirs(folder)
        print("Dossier 'visages' créé. Placez les photos des clients ici.")
        return

    print("🔄 Chargement des visages...")
    temp_encodings = []
    temp_names = []

    for filename in os.listdir(folder):
        if filename.lower().endswith((".jpg", ".png", ".jpeg")):
            try:
                img_path = os.path.join(folder, filename)
                image = face_recognition.load_image_file(img_path)
                encodings = face_recognition.face_encodings(image)
                if encodings:
                    temp_encodings.append(encodings[0])
                    name = os.path.splitext(filename)[0]
                    # Nettoyage des suffixes de pose (_left, _center, etc.) pour garder un ID unique
                    for suffix in ["_center", "_left", "_right", "_up", "_down"]:
                        if name.endswith(suffix):
                            name = name[:-len(suffix)]
                            break
                    temp_names.append(name)
            except Exception as e:
                print(f"Erreur chargement visage {filename}: {e}")
    
    KNOWN_FACE_ENCODINGS = temp_encodings
    KNOWN_FACE_NAMES = temp_names
    print(f"✅ {len(KNOWN_FACE_NAMES)} visages chargés en mémoire.")

load_known_faces()

# --- RECONNAISSANCE INSTANTANÉE DES PRODUITS (STYLE FACE ID) ---
# Au lieu de réentraîner l'IA, on compare les signatures visuelles (ORB Keypoints)
# NOUVEAU SYSTÈME FLANN POUR GRANDE ÉCHELLE (10,000+ Objets)
FLANN_INDEX_LSH = 6
# Paramètres optimisés pour les descripteurs binaires ORB

# SEUIL DE STRICTITUDE COULEUR (Bhattacharyya)
# Plus la valeur est BASSE, plus le système est STRICT (0.0 = identique)
COLOR_STRICTNESS_THRESHOLD = 0.5

KNOWN_PRODUCT_SPECTRAL = {} # Stockage des signatures couleurs
INDEX_PARAMS = dict(algorithm=FLANN_INDEX_LSH, table_number=6, key_size=12, multi_probe_level=1)
SEARCH_PARAMS = dict(checks=50) # Nombre de vérifications (plus haut = plus précis mais plus lent)

PRODUCT_FLANN_MATCHER = None # Le moteur de recherche rapide
KNOWN_PRODUCT_NAMES_LIST = [] # Liste alignée avec l'index FLANN pour retrouver les noms

# Initialisation du détecteur de points d'intérêt (Rapide et Efficace)
ORB = cv2.ORB_create(nfeatures=1000) # Réduit pour gagner en fluidité sans perdre trop de précision

def load_known_products(force_reload=False):
    """Apprend les produits enregistrés dans le dossier dataset sans entraînement."""
    global PRODUCT_FLANN_MATCHER, KNOWN_PRODUCT_NAMES_LIST, KNOWN_PRODUCT_SPECTRAL
    folder = "produits_dataset"
    cache_file = "products_index.pkl"

    if not os.path.exists(folder):
        os.makedirs(folder)
        return

    # 1. TENTATIVE DE CHARGEMENT DEPUIS LE CACHE (Démarrage instantané)
    if not force_reload and os.path.exists(cache_file):
        try:
            print("⚡ Chargement instantané de l'index produits depuis le disque...")
            with open(cache_file, "rb") as f:
                data = pickle.load(f)
                KNOWN_PRODUCT_NAMES_LIST = data["names"]
                descriptors_list = data["descriptors"]
                KNOWN_PRODUCT_SPECTRAL = data.get("spectral", {})
            # On recrée juste le moteur de recherche (très rapide)
            if descriptors_list:
                PRODUCT_FLANN_MATCHER = cv2.FlannBasedMatcher(INDEX_PARAMS, SEARCH_PARAMS)
                PRODUCT_FLANN_MATCHER.add(descriptors_list)
                PRODUCT_FLANN_MATCHER.train()
                print(f"✅ Index chargé du cache : {len(KNOWN_PRODUCT_NAMES_LIST)} modèles.")
                return
        except Exception as e:
            print(f"⚠️ Cache corrompu ou illisible, recalcul en cours... ({e})")

    print("🔄 Indexation haute performance des produits (FLANN)...")
    KNOWN_PRODUCT_NAMES_LIST = []
    descriptors_list = [] # Liste pour FLANN
    KNOWN_PRODUCT_SPECTRAL = {}

    for filename in os.listdir(folder):
        if filename.lower().endswith((".jpg", ".png", ".jpeg")):
            try:
                # Nom fichier ex: coca_front.jpg -> on garde "coca"
                name = filename.split('_')[0] 
                img_path = os.path.join(folder, filename)
                # Lecture en noir et blanc pour l'analyse de texture
                img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
                if img is None: continue
                
                # Lecture couleur pour la signature spectrale
                img_color = cv2.imread(img_path)
                sig = analyze_spectral_signature(img_color)
                
                # Calcul de la signature numérique (Descripteurs)
                kp, des = ORB.detectAndCompute(img, None)
                if des is not None and len(des) > 5: # On ignore les images trop pauvres en détails
                    descriptors_list.append(des)
                    KNOWN_PRODUCT_NAMES_LIST.append(name)
                    if sig:
                        KNOWN_PRODUCT_SPECTRAL[name] = sig
            except Exception as e:
                print(f"Erreur lecture produit {filename}: {e}")
    
    if descriptors_list:
        # Création du moteur FLANN et entraînement sur tous les produits d'un coup
        try:
            # SAUVEGARDE SUR LE DISQUE (Pour la prochaine fois)
            with open(cache_file, "wb") as f:
                pickle.dump({
                    "names": KNOWN_PRODUCT_NAMES_LIST, 
                    "descriptors": descriptors_list,
                    "spectral": KNOWN_PRODUCT_SPECTRAL
                }, f)
            
            PRODUCT_FLANN_MATCHER = cv2.FlannBasedMatcher(INDEX_PARAMS, SEARCH_PARAMS)
            PRODUCT_FLANN_MATCHER.add(descriptors_list)
            PRODUCT_FLANN_MATCHER.train()
            print(f"✅ Base de données indexée : {len(KNOWN_PRODUCT_NAMES_LIST)} modèles prêts (Scalable 10k+).")
        except Exception as e:
            print(f"❌ Erreur Indexation FLANN: {e}")
            PRODUCT_FLANN_MATCHER = None
    else:
        print("⚠️ Aucun produit valide trouvé dans produits_dataset.")

load_known_products()

def analyze_spectral_signature(crop_img):
    """
    Simule une analyse multi-spectrale en calculant la signature 
    colorimétrique unique de l'objet sur plusieurs canaux.
    """
    try:
        # 1. NORMALISATION DE L'ÉCLAIRAGE (CLAHE)
        # On passe en LAB pour traiter la luminance (L) sans toucher aux couleurs (A, B)
        lab = cv2.cvtColor(crop_img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Appliquer CLAHE sur le canal de luminosité
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        
        # Re-fusionner et convertir en HSV pour l'analyse spectrale
        limg = cv2.merge((cl, a, b))
        final_bgr = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        hsv = cv2.cvtColor(final_bgr, cv2.COLOR_BGR2HSV)
        
        # Calcul des histogrammes pour les 3 canaux
        hist_h = cv2.calcHist([hsv], [0], None, [180], [0, 180])
        hist_s = cv2.calcHist([hsv], [1], None, [256], [0, 256])
        
        # Normalisation pour l'indépendance à la taille
        cv2.normalize(hist_h, hist_h, 0, 1, cv2.NORM_MINMAX)
        cv2.normalize(hist_s, hist_s, 0, 1, cv2.NORM_MINMAX)
        
        return {
            "hue": hist_h,
            "sat": hist_s,
            "mean_color": np.mean(final_bgr, axis=(0, 1)).tolist()
        }
    except:
        return None

def identify_product_in_crop(crop_img_pil):
    """Compare une image découpée avec les produits connus."""
    if PRODUCT_FLANN_MATCHER is None or not KNOWN_PRODUCT_NAMES_LIST: return None
    
    # Conversion PIL -> OpenCV Gris
    crop_np = np.array(crop_img_pil)
    crop_bgr = cv2.cvtColor(crop_np, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    
    # Si l'image est trop petite ou floue, on ne tente rien (évite les faux positifs)
    if gray.shape[0] < 50 or gray.shape[1] < 50:
        return None

    kp, des = ORB.detectAndCompute(gray, None)
    if des is None: return None
    
    try:
        # RECHERCHE GLOBALE OPTIMISÉE (O(log N))
        # knnMatch cherche les 2 voisins les plus proches dans TOUTE la base de produits
        matches = PRODUCT_FLANN_MATCHER.knnMatch(des, k=2)
        
        votes = {}
        
        for match_pair in matches:
            if len(match_pair) == 2:
                m, n = match_pair
                # Lowe's Ratio Test (Strict)
                if m.distance < 0.75 * n.distance:
                    # m.imgIdx est l'index de l'image dans KNOWN_PRODUCT_NAMES_LIST
                    product_idx = m.imgIdx
                    if product_idx < len(KNOWN_PRODUCT_NAMES_LIST):
                        name = KNOWN_PRODUCT_NAMES_LIST[product_idx]
                        votes[name] = votes.get(name, 0) + 1
        
        # Quel produit a reçu le plus de votes ?
        if votes:
            best_product = max(votes, key=votes.get)
            score = votes[best_product]
            
            # --- VALIDATION PAR HISTOGRAMME DE COULEUR ---
            if score >= 6 and best_product in KNOWN_PRODUCT_SPECTRAL:
                current_sig = analyze_spectral_signature(crop_bgr)
                ref_sig = KNOWN_PRODUCT_SPECTRAL[best_product]
                
                # Comparaison de l'histogramme de Teinte (Hue)
                # 0 = identique, 1 = totalement différent (Bhattacharyya)
                dist = cv2.compareHist(current_sig['hue'], ref_sig['hue'], cv2.HISTCMP_BHATTACHARYYA)
                
                # Validation basée sur le seuil configuré
                if dist < COLOR_STRICTNESS_THRESHOLD:
                    return best_product
                else:
                    print(f"🔍 Rejet par couleur pour {best_product} (dist: {dist:.2f})")
                
    except Exception as e:
        # print(f"Erreur Matching: {e}") 
        pass
        
    return None

# --- FONCTIONS DE GESTION DES PRODUITS ---

def sync_products_from_google():
    """Récupère la liste des produits depuis Google Sheets."""
    global DB_PRODUITS
    try:
        response = requests.post(APPS_SCRIPT_URL, json={"action": "getProducts"})
        if response.status_code == 200:
            DB_PRODUITS = response.json()
            print(f"✅ {len(DB_PRODUITS)} produits chargés depuis Google Sheets.")
        else:
            print("⚠️ Erreur synchronisation produits.")
    except Exception as e:
        print(f"⚠️ Impossible de joindre Google Sheets : {e}")

# --- MOTEUR D'ANALYSE EN ARRIÈRE-PLAN (THREAD) ---
# Utilisation d'un Pool de Threads pour traiter 4 caméras en parallèle
AI_EXECUTOR = ThreadPoolExecutor(max_workers=4)
PROCESSING_CAMS = set() # Pour éviter d'analyser deux fois la même caméra en même temps

def run_ai_analysis(cam_id, img_bytes):
    """Exécute l'IA pour une caméra spécifique."""
    try:
        img_pil = Image.open(io.BytesIO(img_bytes))
        LAST_DETECTIONS[cam_id] = process_pick_and_go_logic(cam_id, img_pil)
    except Exception as e:
        print(f"Erreur analyse frame {cam_id}: {e}")
    finally:
        PROCESSING_CAMS.discard(cam_id)

def background_analysis_loop():
    """Ce processus tourne tout seul et analyse les images sans bloquer la vidéo."""
    print("🚀 Moteur IA démarré en arrière-plan (Mode Fluide).")
    while True:
        try:
            active_cams = list(LATEST_FRAME_BYTES.keys())
            for cam_id in active_cams:
                if cam_id not in PROCESSING_CAMS:
                    img_bytes = LATEST_FRAME_BYTES.get(cam_id)
                    if img_bytes and MODEL is not None:
                        PROCESSING_CAMS.add(cam_id)
                        AI_EXECUTOR.submit(run_ai_analysis, cam_id, img_bytes)
            
            time.sleep(0.01) # Fréquence de scrutation élevée
        except Exception as e:
            print(f"Erreur Thread IA: {e}")
            time.sleep(1)

# Charger les produits au démarrage
sync_products_from_google()

def add_product_to_google(name, price):
    """Envoie un nouveau produit à Google Sheets."""
    try:
        payload = {
            "action": "addProduct",
            "payload": {"name": name, "price": int(price)}
        }
        requests.post(APPS_SCRIPT_URL, json=payload)
        # Mise à jour locale immédiate
        DB_PRODUITS[name.lower()] = price
        return True
    except Exception as e:
        print(f"Erreur ajout produit: {e}")
        return False

def register_client_google(name):
    """Envoie le nouveau client à Google Sheets (Inscription)."""
    try:
        payload = {
            "action": "registerClient",
            "payload": {"name": name, "balance": 5000}
        }
        requests.post(APPS_SCRIPT_URL, json=payload)
    except Exception as e:
        print(f"⚠️ Erreur Google Sync (Inscription): {e}")

def send_image_to_google(filename, image_bytes):
    """Envoie une image (Visage ou Produit) à Google Apps Script pour sauvegarde Drive."""
    if not APPS_SCRIPT_URL or "script.google.com" not in APPS_SCRIPT_URL:
        print(f"⚠️ Cloud désactivé ou URL invalide. Image {filename} locale uniquement.")
        return

    try:
        b64_img = base64.b64encode(image_bytes).decode('utf-8')
        payload = {
            "action": "uploadImage",
            "payload": {
                "filename": filename,
                "image": b64_img
            }
        }
        resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        if resp.status_code == 200:
            print(f"📤 Image {filename} envoyée avec succès au Cloud (Google Drive).")
        else:
            print(f"⚠️ Erreur Cloud {filename} (Status: {resp.status_code})")
    except Exception as e:
        print(f"⚠️ Erreur Envoi Image Google: {e}")

def encode_image(image_bytes):
    """Encode l'image en base64 pour l'API Groq."""
    return base64.b64encode(image_bytes).decode('utf-8')

def draw_overlays(image_bytes, text_lines):
    """Dessine du texte (HUD) sur l'image style CCTV."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convertir en RGBA pour la transparence
        img = img.convert("RGBA")
        
        # Calque pour les dessins semi-transparents
        overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Essayer de charger une police par défaut, sinon défaut système
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except:
            font = ImageFont.load_default()

        # 1. En-tête type CCTV (Bande noire en haut)
        draw.rectangle([(0, 0), (img.width, 30)], fill=(0, 0, 0, 255))
        timestamp = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        draw.text((10, 8), f"REC  {timestamp}", font=font, fill="#FF0000")

        # Fond sombre semi-transparent en haut à gauche pour le texte
        # On le descend un peu pour ne pas cacher l'en-tête CCTV
        draw.rectangle([(5, 35), (250, 40 + len(text_lines)*30)], fill=(0, 0, 0, 150))

        y = 40
        for line in text_lines:
            # Texte vert néon
            draw.text((15, y), line, font=font, fill="#00FF41") 
            y += 30
        
        # Fusionner l'image originale et l'overlay
        img = Image.alpha_composite(img, overlay)
        img = img.convert("RGB") # Revenir en JPEG compatible
        
        # Convertir l'image modifiée en bytes pour l'affichage web
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()
    except Exception as e:
        print(f"Erreur dessin: {e}")
        return image_bytes

@app.get("/")
async def root():
    """Sert la page d'accueil moderne DALL JAMM."""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return RedirectResponse(url="/admin")

@app.get("/api/export_transactions")
async def export_transactions():
    """Génère et télécharge un fichier CSV des transactions du jour."""
    if not os.path.exists(TRANSACTIONS_FILE):
        return {"error": "Aucune transaction enregistrée."}
    
    with open(TRANSACTIONS_FILE, "r") as f:
        data = json.load(f)
    
    output_file = f"export_transactions_{datetime.date.today()}.csv"
    with open(output_file, "w", newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "userID", "produit", "montant", "action", "camera"])
        writer.writeheader()
        writer.writerows(data)
            
    return FileResponse(output_file, media_type="text/csv", filename=output_file)

@app.get("/client_frontend", response_class=HTMLResponse)
async def client_frontend_interface():
    return RedirectResponse(url="/client")

@app.get("/manager_frontend", response_class=HTMLResponse)
async def manager_frontend_interface():
    return await manager_dashboard()

@app.get("/api/client_data/{user_id}")
async def get_client_data(user_id: str):
    """API pour récupérer les données d'un client (solde, transactions)."""
    if user_id not in WALLETS:
        raise HTTPException(status_code=404, detail="Client non trouvé")
    
    client_transactions = []
    if os.path.exists(TRANSACTIONS_FILE):
        with open(TRANSACTIONS_FILE, "r") as f:
            try:
                all_transactions = json.load(f)
                for t in all_transactions:
                    if t.get("userID") == user_id:
                        client_transactions.append(t)
            except:
                pass # Fichier vide ou corrompu
    
    return {
        "name": user_id,
        "balance": WALLETS[user_id],
        "transactions": client_transactions
    }

@app.get("/api/products_data")
async def get_products_data():
    """API pour récupérer la liste des produits."""
    products_list = []
    for name, price in DB_PRODUITS.items():
        products_list.append({"name": name.capitalize(), "price": price})
    return products_list

@app.post("/api/login")
async def api_login(phone: str = Form(...), password: str = Form(...)):
    """Vérifie les identifiants auprès d'Apps Script."""
    payload = {"action": "login", "payload": {"phone": phone, "password": password}}
    try:
        resp = requests.post(APPS_SCRIPT_URL, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            return {"status": "success", "user_data": data.get("user_data")}
        raise HTTPException(status_code=401, detail=data.get("message", "Identifiants incorrects"))
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=503, detail="Base de données Google Sheets injoignable.")
    except Exception as e:
        print(f"Erreur login server: {e}")
        raise HTTPException(status_code=500, detail="Erreur de communication avec la base de données")


@app.post("/api/update_password")
async def api_update_password(phone: str = Form(...), new_password: str = Form(...)):
    """Met à jour le mot de passe de l'utilisateur via Apps Script."""
    try:
        payload = {
            "action": "updatePassword",
            "payload": {"phone": phone, "newPassword": new_password}
        }
        threading.Thread(target=lambda: requests.post(APPS_SCRIPT_URL, json=payload), daemon=True).start()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/add_product_api")
async def add_product_api(product_name: str = Form(...), price: int = Form(...)):
    """API pour ajouter un produit depuis le frontend manager."""
    if add_product_to_google(product_name, price):
        # Recharger les produits pour que le système d'IA les connaisse
        load_known_products(force_reload=True)
        return {"status": "success", "message": "Produit ajouté avec succès"}
    else:
        raise HTTPException(status_code=500, detail="Erreur lors de l'ajout du produit")

@app.post("/api/register_simple_api")
async def api_register_simple_api(name: str = Form(...), email: str = Form(""), balance: int = Form(5000)):
    """API d'inscription simple sans photo, utilisée par le frontend."""
    try:
        WALLETS[name] = balance
        save_wallets()
        
        payload = {
            "action": "registerUser",
            "payload": {"name": name, "email": email, "balance": balance}
        }
        threading.Thread(target=lambda: requests.post(APPS_SCRIPT_URL, json=payload), daemon=True).start()
        
        return {"status": "success", "userId": name}
    except Exception as e:
        print(f"Erreur d'inscription: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'inscription.")

# Mise à jour des liens dans le Hub pour pointer vers les nouvelles interfaces
app.get("/client")(lambda: RedirectResponse(url="/client_frontend"))
app.get("/manager")(lambda: RedirectResponse(url="/manager_frontend"))

@app.get("/register", response_class=HTMLResponse)
async def register_interface():
    """Interface d'inscription Hyflex (Visage + QR + Google)."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
    <title>HYFLEX - INSCRIPTION</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ background: #0a0a0b; color: #fff; font-family: 'Inter', sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
        .container {{ width: 92%; max-width: 420px; background: rgba(20, 20, 25, 0.8); backdrop-filter: blur(10px); padding: 30px; border: 1px solid #222; border-radius: 20px; box-shadow: 0 20px 50px rgba(0,0,0,0.5); text-align: center; }}
        h1 { color: #00f2ff; margin-bottom: 20px; font-size: 1.6em; text-transform: uppercase; letter-spacing: 2px; font-weight: 800; }
        input {{ width: 100%; padding: 15px; margin: 10px 0; background: #16161a; border: 1px solid #333; color: white; border-radius: 12px; box-sizing: border-box; font-size: 1.1em; text-align: center; transition: 0.3s; }}
        input:focus { border-color: #00f2ff; outline: none; background: #1a1a1a; }
        #video-box {{ width: 100%; height: 320px; background: #000; border: 1px solid #00f2ff; margin-bottom: 20px; position: relative; overflow: hidden; border-radius: 15px; }}
        video {{ width: 100%; height: 100%; object-fit: cover; filter: brightness(1.1); }}
        .btn { background: #00f2ff; color: #000; border: none; padding: 15px; width: 100%; font-weight: bold; font-size: 1.2em; border-radius: 8px; cursor: pointer; text-transform: uppercase; transition: 0.3s; margin-top: 10px; display: block; }
        .btn:hover { background: #fff; box-shadow: 0 0 20px #00f2ff; transform: scale(1.02); }
        .status { margin-top: 20px; font-size: 1em; color: #aaa; font-weight: 500; }
        .success { color: #00ff41; }
        .error { color: #ff3333; }
        .qr-box { margin-top: 25px; padding: 15px; background: white; display: none; border-radius: 8px; animation: fadeIn 0.5s; }
        .qr-box img { width: 100%; max-width: 180px; display: block; margin: 0 auto; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        
        /* Guide visuel pour les poses */
        .guide-overlay { position: absolute; top: 10px; left: 10px; background: rgba(0,0,0,0.7); padding: 5px 10px; border-radius: 4px; color: #00f2ff; font-weight: bold; pointer-events: none; }
        .progress-bar { width: 100%; height: 5px; background: #333; margin-top: 10px; border-radius: 3px; overflow: hidden; }
        .progress-fill { height: 100%; background: #00f2ff; width: 0%; transition: width 0.3s; }
        .back-hub {{ margin-top: 25px; display: block; color: #555; text-decoration: none; font-size: 0.8em; }}
    </style>
    </head>
    <body>
        <div class="container">
            <h1>🛡️ FACE ID SETUP</h1>
            <div id="video-box">
                <video id="vid" autoplay muted playsinline></video>
                <div class="guide-overlay" id="guide-text">Étape 1/5 : Regardez au CENTRE</div>
            </div>
            <div class="progress-bar"><div class="progress-fill" id="progress"></div></div>
            
            <input type="text" id="name" placeholder="NOM & PRÉNOM" autocomplete="off">
            <button class="btn" id="btn-action" onclick="startSequence()">COMMENCER LE SCAN</button>
            <div class="status" id="status">En attente de saisie...</div>
            <div id="qr-result" class="qr-box"></div>
            <a href="/" class="back-hub">Hub Principal</a>
        </div>
        <canvas id="cvs" style="display:none"></canvas>
        <script>
            const video = document.getElementById('vid');
            const canvas = document.getElementById('cvs');
            const status = document.getElementById('status');
            const qrResult = document.getElementById('qr-result');
            const guideText = document.getElementById('guide-text');
            const progress = document.getElementById('progress');
            const btn = document.getElementById('btn-action'); 
            navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } })
            .then(stream => video.srcObject = stream)
            .catch(err => status.innerText = "Erreur Camera: " + err);

            const steps = [
                { pose: "center", text: "Regardez au CENTRE" },
                { pose: "left", text: "Tournez légèrement à GAUCHE ⬅️" },
                { pose: "right", text: "Tournez légèrement à DROITE ➡️" },
                { pose: "up", text: "Regardez vers le HAUT ⬆️" },
                { pose: "down", text: "Regardez vers le BAS ⬇️" }
            ];
            let currentStep = 0;

            async function startSequence() {
                const name = nameInput.value;
                if(!name) { status.innerText = "⚠️ Veuillez entrer votre nom !"; return; }
                
                // Désactiver l'input pendant le processus
                nameInput.disabled = true;
                btn.onclick = captureStep;
                currentStep = 0;
                updateUI();
            }

            function updateUI() {
                if (currentStep >= steps.length) {
                    finishRegistration();
                    return;
                }
                const step = steps[currentStep];
                guideText.innerText = `Étape ${currentStep + 1}/5 : ${step.text}`;
                btn.innerText = "📸 CAPTURER";
                progress.style.width = ((currentStep / steps.length) * 100) + "%";
                status.innerHTML = "Positionnez-vous et cliquez.";
            }

            async function captureStep() {
                const name = nameInput.value;
                const step = steps[currentStep];
                
                status.innerHTML = "⏳ Analyse biométrique en cours...";
                
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0);
                
                canvas.toBlob(async (blob) => {
                    const formData = new FormData();
                    formData.append('user_id', name);
                    formData.append('pose', step.pose); // Envoi de la pose (center, left, etc.)
                    formData.append('file', blob, name + '_' + step.pose + '.jpg');
                    
                    try {
                        const res = await fetch('/api/signup', { method: 'POST', body: formData });
                        const data = await res.json();
                        if(data.status === 'success') {
                            currentStep++;
                            updateUI();
                        } else {
                            status.innerHTML = "<span class='error'>❌ " + (data.detail || "Erreur capture") + "</span>";
                        }
                    } catch(e) {
                        status.innerHTML = "<span class='error'>❌ Erreur réseau</span>";
                    }
                }, 'image/jpeg', 0.9);
            }

            function finishRegistration() {
                progress.style.width = "100%";
                guideText.innerText = "✅ TERMINÉ !";
                btn.style.display = "none";
                status.innerHTML = "<span class='success'>✅ COMPTE CONFIGURÉ & SYNC GOOGLE !</span>";
                
                const name = nameInput.value;
                const qrUrl = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=" + encodeURIComponent(name);
                qrResult.innerHTML = "<img src='" + qrUrl + "'><br><strong style='color:#000; display:block; margin-top:10px;'>PASS HYFLEX</strong><small style='color:#555'>" + name + "</small>";
                qrResult.style.display = "block";
                nameInput.value = "";
                nameInput.disabled = false;
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/register_simple", response_class=HTMLResponse)
async def register_simple_interface():
    """Interface d'inscription classique (Nom, Email, Solde)."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
    <title>HYFLEX - INSCRIPTION CLASSIQUE</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #050505; color: #fff; font-family: 'Segoe UI', sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
        .container { width: 90%; max-width: 400px; background: #111; padding: 25px; border: 1px solid #333; border-radius: 12px; box-shadow: 0 0 30px rgba(255, 153, 0, 0.15); text-align: center; }
        h1 { color: #ff9900; margin-bottom: 20px; font-size: 1.6em; text-transform: uppercase; letter-spacing: 2px; font-weight: 800; }
        input { width: 100%; padding: 15px; margin: 10px 0; background: #222; border: 1px solid #444; color: white; border-radius: 8px; box-sizing: border-box; font-size: 1.1em; text-align: center; }
        input:focus { border-color: #ff9900; outline: none; background: #1a1a1a; }
        .btn { background: #ff9900; color: #000; border: none; padding: 15px; width: 100%; font-weight: bold; font-size: 1.2em; border-radius: 8px; cursor: pointer; text-transform: uppercase; transition: 0.3s; margin-top: 10px; display: block; }
        .btn:hover { background: #fff; box-shadow: 0 0 20px #ff9900; transform: scale(1.02); }
        .status { margin-top: 20px; font-size: 1em; color: #aaa; }
        .back-link { margin-top: 20px; display: block; color: #00f2ff; text-decoration: none; font-size: 0.9em; }
    </style>
    </head>
    <body>
        <div class="container">
            <h1>📝 NOUVEAU CLIENT</h1>
            <form id="regForm">
                <input type="text" id="name" name="name" placeholder="NOM COMPLET" required>
                <input type="email" id="email" name="email" placeholder="EMAIL (OPTIONNEL)">
                <input type="number" id="balance" name="balance" placeholder="SOLDE INITIAL (FCFA)" value="5000">
                <button type="submit" class="btn">CRÉER LE COMPTE</button>
            </form>
            <div class="status" id="status"></div>
            <a href="/" class="back-link">⬅ Retour au Hub</a>
        </div>
        <script>
            document.getElementById('regForm').onsubmit = async (e) => {
                e.preventDefault();
                const status = document.getElementById('status');
                status.innerText = "⏳ Inscription en cours...";
                
                const formData = new FormData();
                formData.append('name', document.getElementById('name').value);
                formData.append('email', document.getElementById('email').value);
                formData.append('balance', document.getElementById('balance').value);
                
                try {
                    const res = await fetch('/api/register_simple', { method: 'POST', body: formData });
                    const data = await res.json();
                    if(data.status === 'success') {
                        status.innerHTML = "<span style='color:#00ff41'>✅ Client enregistré !</span>";
                        document.getElementById('regForm').reset();
                    } else {
                        status.innerHTML = "<span style='color:#ff3333'>❌ Erreur: " + data.message + "</span>";
                    }
                } catch(e) {
                    status.innerHTML = "<span style='color:#ff3333'>❌ Erreur réseau</span>";
                }
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/api/register_simple")
async def api_register_simple(name: str = Form(...), email: str = Form(""), balance: int = Form(5000)):
    """API d'inscription simple sans photo."""
    try:
        # Mise à jour locale du Wallet
        WALLETS[name] = balance
        save_wallets()
        
        # Synchronisation avec Google Sheets (Action registerUser existante dans Apps Script)
        payload = {
            "action": "registerUser",
            "payload": {"name": name, "email": email, "balance": balance}
        }
        threading.Thread(target=lambda: requests.post(APPS_SCRIPT_URL, json=payload), daemon=True).start()
        
        return {"status": "success", "userId": name}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def blocking_face_check(content):
    """Vérification synchrone du visage pour éviter de bloquer le serveur."""
    try:
        image = face_recognition.load_image_file(io.BytesIO(content))
        return len(face_recognition.face_encodings(image)) > 0
    except:
        return False

@app.post("/api/signup")
async def signup_client(user_id: str = Form(...), pose: str = Form("center"), file: UploadFile = File(...)):
    """API d'inscription : Enregistre le visage et notifie Google Apps Script."""
    folder = "visages"
    if not os.path.exists(folder): os.makedirs(folder)
    
    content = await file.read()

    if FACE_REC_AVAILABLE:
        try:
            is_face_valid = await asyncio.to_thread(blocking_face_check, content)
            if not is_face_valid:
                return {"status": "error", "detail": "Aucun visage détecté. Réessayez."}
        except Exception as e:
            print(f"Erreur validation: {e}")
            pass

    filename = f"{user_id}_{pose}.jpg"
    file_path = os.path.join(folder, filename)
    
    with open(file_path, "wb") as f:
        f.write(content)

    threading.Thread(target=send_image_to_google, args=(f"FACE_{filename}", content), daemon=True).start()

    if FACE_REC_AVAILABLE:
        await asyncio.to_thread(load_known_faces)
        
    if user_id not in WALLETS:
        WALLETS[user_id] = 5000
        save_wallets()
        threading.Thread(target=register_client_google, args=(user_id,), daemon=True).start()
    
    print(f"✅ Enregistrement Biométrique : {user_id} ({pose}) - OK")
    
    return {"status": "success", "user_id": user_id, "pose": pose}

def identify_person_in_image(image_input):
    """Identifie une personne dans l'image."""
    if not FACE_REC_AVAILABLE or not KNOWN_FACE_ENCODINGS:
        return "Client_Unknown"
    
    try:
        # Supporte image_bytes ou PIL Image/Numpy via face_recognition
        if isinstance(image_input, bytes):
            image_input = io.BytesIO(image_input)
        elif isinstance(image_input, Image.Image):
            image_input = np.array(image_input)
            
        unknown_image = face_recognition.load_image_file(image_input) if not isinstance(image_input, np.ndarray) else image_input
        
        # AMÉLIORATION DISTANCE : On demande à chercher des visages plus petits (upsample=2)
        face_locations = face_recognition.face_locations(unknown_image, number_of_times_to_upsample=2)
        unknown_encodings = face_recognition.face_encodings(unknown_image, face_locations)

        if unknown_encodings:
            face_encoding = unknown_encodings[0]
            matches = face_recognition.compare_faces(KNOWN_FACE_ENCODINGS, face_encoding, tolerance=0.5) # Ajusté pour la distance
            if True in matches:
                first_match_index = matches.index(True)
                return KNOWN_FACE_NAMES[first_match_index]
    except Exception as e:
        print(f"Erreur reco faciale: {e}")

    return "Client_Unknown"


def log_transaction_via_api(payload):
    """Enregistre la transaction en appelant l'API Google Apps Script."""
    for attempt in range(3): # Tentative de reconnexion auto (3 essais)
        try:
            api_payload = {
                "action": "logTransaction",
                "payload": payload
            }
            save_transaction_local(payload) 
            response = requests.post(APPS_SCRIPT_URL, json=api_payload, timeout=12)
            response.raise_for_status() 
            print(f"✅ Transaction enregistrée sur Google Sheets (Essai {attempt+1}): {response.json()}")
            return 
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                 print(f"🚨 ERREUR PERMISSION (401): Google refuse l'accès.")
                 break
            print(f"⚠️ Erreur HTTP (Essai {attempt+1}): {e}")
        except Exception as e:
            print(f"⚠️ Erreur Réseau/Google (Essai {attempt+1}): {e}")
        time.sleep(2)


def process_pick_and_go_logic(camera_id, img):
    """Analyse l'image, suit les objets et détecte les achats."""
    global SHELF_STATE
    
    if MODEL is None:
        return []
    
    # 0. PRÉPARATION DES DONNÉES (Conversion PIL -> Numpy pour OpenCV/MediaPipe)
    img_cv = np.array(img) # Convertit l'image PIL en matrice RGB
    height, width, _ = img_cv.shape
    
    detections_to_draw = []
    person_count = 0

    # --- ÉTAPE 1.5 : DÉTECTION DU CORPS ENTIER (MediaPipe Pose) ---
    pose_landmarks = None
    if POSE_DETECTOR:
        pose_results = POSE_DETECTOR.process(img_cv)
        if pose_results.pose_landmarks:
            pose_landmarks = pose_results.pose_landmarks
            detections_to_draw.append({
                "type": "pose",
                "landmarks": pose_landmarks
            })
    
    # --- ÉTAPE 1 : TRACKING YOLO ---
    res = None
    try:
        # Utilisation de half=True pour doubler la vitesse sur les cartes graphiques modernes
        results = MODEL.track(img, persist=True, verbose=False, conf=0.6, iou=0.5, 
                             tracker="botsort.yaml", imgsz=640, half=True)
        res = results[0]
    except Exception:
        return []

    # Dictionnaires temporaires pour cette frame
    person_boxes_ids = [] # List of (box, track_id)
    
    # --- ÉTAPE 2 : IDENTIFICATION DES PERSONNES ET LIEN TRACK_ID ---
    if res.boxes.id is not None:
        boxes = res.boxes.xyxy.cpu().numpy().astype(int)
        ids = res.boxes.id.cpu().numpy().astype(int)
        cls = res.boxes.cls.cpu().numpy().astype(int)
        
        for box, tid, cid in zip(boxes, ids, cls):
            if res.names[cid] == "person":
                person_count += 1
                person_boxes_ids.append((box, tid))
                
                # Si on ne connaît pas encore le nom de cet ID de tracking
                if camera_id not in PERSON_TRACK_MEMORY: PERSON_TRACK_MEMORY[camera_id] = {}
                
                # Optimisation : On ne tente l'identification que 10 fois max ou si pas encore reconnu
                if tid not in PERSON_TRACK_MEMORY.get(camera_id, {}) or PERSON_TRACK_MEMORY[camera_id][tid] == "Client_Unknown":
                    attempts = PERSON_ID_ATTEMPTS.get(f"{camera_id}_{tid}", 0)
                    if attempts < 5: # Réduit à 5 tentatives pour économiser le CPU
                        p_crop = img.crop((box[0], box[1], box[2], box[3]))
                        name = identify_person_in_image(p_crop)
                        if name != "Client_Unknown":
                            PERSON_TRACK_MEMORY[camera_id][tid] = name
                        PERSON_ID_ATTEMPTS[f"{camera_id}_{tid}"] = attempts + 1
                    elif tid not in PERSON_TRACK_MEMORY[camera_id]:
                        # Si après 5 essais on ne sait pas, on marque inconnu pour cette session
                        name = "Client_Unknown"
                        PERSON_TRACK_MEMORY[camera_id][tid] = name
                
                # --- SUIVI DU GESTE (TRAJECTOIRE) ---
                if pose_landmarks:
                    # On cherche le point du poignet le plus visible (15: gauche, 16: droit)
                    l_wrist = pose_landmarks.landmark[15]
                    r_wrist = pose_landmarks.landmark[16]
                    active_lm = l_wrist if l_wrist.visibility > r_wrist.visibility else r_wrist
                    if active_lm.visibility > 0.5:
                        px, py = int(active_lm.x * width), int(active_lm.y * height)
                        if camera_id not in GESTURE_PATHS: GESTURE_PATHS[camera_id] = {}
                        if tid not in GESTURE_PATHS[camera_id]: GESTURE_PATHS[camera_id][tid] = []
                        GESTURE_PATHS[camera_id][tid].append((px, py))
                        if len(GESTURE_PATHS[camera_id][tid]) > 15: GESTURE_PATHS[camera_id][tid].pop(0)

    # --- ÉTAPE 3 : DÉTECTION DES MAINS ET LIEN AVEC LES PERSONNES ---
    hand_to_person_track_id = {} # {hand_index: person_track_id}
    if FACE_REC_AVAILABLE:
        pass # (Logique face recognition déplacée plus haut dans le tracking)

    hand_positions = [] # Pour stocker le bout des doigts (Index)
    is_grabbing_list = [] # Pour savoir si chaque main est fermée (pinch)
    
    # 1. DÉTECTION DES MAINS (MediaPipe)
    if HAND_DETECTOR:
        hand_results = HAND_DETECTOR.process(img_cv)
        if hand_results.multi_hand_landmarks:
            for hand_landmarks in hand_results.multi_hand_landmarks:
                # On ajoute la main à la liste des dessins
                detections_to_draw.append({
                    "type": "hand",
                    "landmarks": hand_landmarks
                })
                # On récupère la position du bout de l'index (Point 8) pour vérifier s'il touche un objet
                index_tip = hand_landmarks.landmark[8]
                thumb_tip = hand_landmarks.landmark[4]

                # Calcul de la distance entre le pouce et l'index (Geste de pince/saisie)
                # On utilise la distance Euclidienne simple
                distance = math.sqrt((index_tip.x - thumb_tip.x)**2 + (index_tip.y - thumb_tip.y)**2)
                
                # Si distance < 0.1 (10% de l'image), on considère que la main tient quelque chose
                hand_positions.append((int(index_tip.x * width), int(index_tip.y * height)))
                is_grabbing_list.append(distance < 0.1) 
                
                # Trouver à quelle personne appartient cette main
                hx, hy = int(index_tip.x * width), int(index_tip.y * height)
                for p_box, p_tid in person_boxes_ids:
                    if p_box[0] < hx < p_box[2] and p_box[1] < hy < p_box[3]:
                        hand_to_person_track_id[len(hand_positions)-1] = p_tid
                        break

    # --- ÉTAPE 4 : LOGIQUE PRODUITS ET INTERACTIONS ---
    if camera_id not in SHELF_STATE: SHELF_STATE[camera_id] = {}
    
    current_visible_ids = set()
    
    # 2. METTRE À JOUR LES OBJETS VISIBLES
    if res.boxes.id is not None:
        boxes = res.boxes.xyxy.cpu().numpy().astype(int)
        ids = res.boxes.id.cpu().numpy().astype(int)
        cls = res.boxes.cls.cpu().numpy().astype(int)
        
        for box, track_id, class_id in zip(boxes, ids, cls):
            name = res.names[class_id]
            x1, y1, x2, y2 = box
            
            if name == "person":
                # Dessiner le cadre de la personne identifiée
                p_name = PERSON_TRACK_MEMORY.get(camera_id, {}).get(track_id, "Inconnu")
                detections_to_draw.append({"type": "box", "box": box, "label": f"👤 {p_name}", "color": "#00f2ff" if p_name != "Inconnu" else "#fff"})
                continue # On ne traite pas l'humain comme un produit à acheter
                
            # GESTION DES PRODUITS
            current_visible_ids.add(track_id)

            # Mise à jour / Ajout dans la mémoire
            if track_id not in SHELF_STATE[camera_id]:
                SHELF_STATE[camera_id][track_id] = {
                "class": name,
                "missing_frames": 0,
                "last_seen": time.time(),
                "id_attempts": 0,
                "confirm_count": 0,
                "is_being_taken": False
            }
            
            # --- IDENTIFICATION FINE (OBJET PAR OBJET) ---
            # Tentative d'identification FLANN limitée pour économiser le CPU
            if "real_label" not in SHELF_STATE[camera_id][track_id] and SHELF_STATE[camera_id][track_id]["id_attempts"] < 5:
                try:
                    crop = img.crop((x1, y1, x2, y2))
                    label = identify_product_in_crop(crop)
                    if label:
                        SHELF_STATE[camera_id][track_id]["real_label"] = label
                    SHELF_STATE[camera_id][track_id]["id_attempts"] += 1
                except: pass

            current_label = SHELF_STATE[camera_id][track_id].get("real_label", name)
            
            # LOGIQUE D'INTERACTION : Est-ce qu'une main touche cet objet ?
            is_touched = False
            is_taken = False # L'objet est-il saisi ?
            
            # Centre de l'objet pour les vecteurs
            obj_cx = (x1 + x2) // 2
            obj_cy = (y1 + y2) // 2
            
            for h_idx, ((hx, hy), grabbing) in enumerate(zip(hand_positions, is_grabbing_list)):
                # Si le doigt est à l'intérieur de la boîte de l'objet
                if x1 < hx < x2 and y1 < hy < y2:
                    is_touched = True
                    if grabbing:
                        is_taken = True
                        SHELF_STATE[camera_id][track_id]["is_being_taken"] = True
                        # On incrémente le compteur de confiance si l'objet est saisi
                        SHELF_STATE[camera_id][track_id]["confirm_count"] += 1
                        
                        # On mémorise quelle personne a pris cet objet
                        if h_idx < len(hand_positions) and h_idx in hand_to_person_track_id:
                            SHELF_STATE[camera_id][track_id]["last_person_tid"] = hand_to_person_track_id[h_idx]
                    
                    # AJOUT VECTEUR VISUEL (Ligne main -> objet)
                    detections_to_draw.append({
                        "type": "vector",
                        "start": (hx, hy),
                        "end": (obj_cx, obj_cy),
                        "color": "#00f2ff" if is_taken else "#FF0000",
                        "state": "taken" if is_taken else "touched"
                    })
                    break

            # DÉFINITION DES COULEURS ET ÉTATS
            color = "#00FF41" # Vert (Repos) par défaut
            if is_taken:
                color = "#00f2ff" # Bleu Cyan (PRIS !) - Validation
            elif is_touched:
                color = "#FF0000" # Rouge (Touché seulement)
            
            # Affichage enrichi : NOM + PRIX
            # On utilise le 'current_label' qui peut être le nom précis (Coca)
            display_name = current_label
            price_info = DB_PRODUITS.get(display_name.lower(), "??")
            label_text = f"{'PRIS ' if is_taken else ''}{display_name.upper()} : {price_info} FCFA"

            # Dessin simple de la bounding box sur l'image de retour
            detections_to_draw.append({
                "type": "box",
                "box": box,
                "label": f"MATCH: {current_label} (ID:{track_id})",
                "color": "#00f2ff",}) # Bleu néon pour "Confirmé"

    # Mise à jour du compteur global pour cette caméra dans les infos de feed
    if camera_id in CAMERA_FEEDS:
        CAMERA_FEEDS[camera_id]["person_count"] = person_count
    else:
        CAMERA_FEEDS[camera_id] = {"person_count": person_count}

    # 3. DÉTECTION DES DISPARITIONS (LOGIQUE D'ACHAT)
    # On regarde les objets qu'on connaissait mais qui ne sont plus là
    known_ids = list(SHELF_STATE[camera_id].keys())
    
    for track_id in known_ids:
        if track_id not in current_visible_ids:
            SHELF_STATE[camera_id][track_id]["missing_frames"] += 1

            # LOGIQUE TURBO : On valide l'achat après 15 frames de disparition 
            # mais UNIQUEMENT si l'objet a été bien identifié auparavant
            if SHELF_STATE[camera_id][track_id]["missing_frames"] == 15:
                product_name = SHELF_STATE[camera_id][track_id].get("real_label", SHELF_STATE[camera_id][track_id]["class"])
                price = DB_PRODUITS.get(product_name.lower(), 0)
                
                # Sécurité persistence : L'IA doit avoir confirmé l'objet au moins 10 fois
                if SHELF_STATE[camera_id][track_id].get("confirm_count", 0) < 10:
                    continue

                # Sécurité : Éviter d'enregistrer des produits inconnus ou à prix nul
                # Nettoyage des chaînes pour éviter les erreurs de comparaison
                if not product_name or str(price) == "0" or "no label" in product_name.lower():
                    print(f"⚠️ Achat ignoré (Produit non identifié ou prix 0) : {product_name}")
                    continue

                # RETROUVER L'ACHETEUR VIA TRACKING
                p_tid = SHELF_STATE[camera_id][track_id].get("last_person_tid")
                user_id = "Client_Unknown"
                if p_tid and camera_id in PERSON_TRACK_MEMORY and p_tid in PERSON_TRACK_MEMORY[camera_id]:
                    user_id = PERSON_TRACK_MEMORY[camera_id][p_tid]
                
                # 2. Si échec ou pas de reco, on regarde si un humain a assigné cette caméra
                if user_id == "Client_Unknown" and camera_id in CAMERA_USER_ASSIGNMENTS:
                    user_id = CAMERA_USER_ASSIGNMENTS[camera_id]
                
                print(f"💰 ACHAT DÉTECTÉ ! {product_name} (ID: {track_id}) - Prix: {price} - Client: {user_id}")
                
                # DÉBIT DU WALLET LOCAL
                if user_id not in WALLETS:
                    WALLETS[user_id] = 5000 # Solde par défaut pour nouveau client
                    
                if user_id in WALLETS:
                    WALLETS[user_id] -= int(price)
                    save_wallets() # Sauvegarde immédiate

                # Envoi à Google Sheets
                payload = {
                    "userID": user_id, 
                    "produit": product_name,
                    "montant": price,
                    "action": "achat",
                    "camera": camera_id
                }
                # Utilisation d'un thread dédié pour l'envoi API afin de ne pas bloquer l'analyse IA
                threading.Thread(target=log_transaction_via_api, args=(payload,), daemon=True).start()
            
            # Si disparu depuis trop longtemps (ex: 100 frames), on l'oublie pour nettoyer la mémoire
            if SHELF_STATE[camera_id][track_id]["missing_frames"] > 100:
                del SHELF_STATE[camera_id][track_id]
        else:
            # L'objet est là, on reset le compteur de disparition
            SHELF_STATE[camera_id][track_id]["missing_frames"] = 0

    return detections_to_draw

def draw_hud(img, detections):
    """Dessine les rectangles style HUD Cyberpunk sur l'image PIL."""
    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        font = ImageFont.load_default()
        
    # On dessine d'abord les objets, puis les mains par dessus
    for det in detections:
        if det['type'] == 'box':
            x1, y1, x2, y2 = det['box']
            color = det['color']
            
            # Couleur de remplissage dynamique
            if color == "#00f2ff": # PRIS (Bleu)
                 fill_color = (0, 242, 255, 80)
            else: # REPOS (Vert)
                fill_color = (0, 255, 65, 40)
            
            # 1. Rectangle semi-transparent
            draw.rectangle([x1, y1, x2, y2], fill=fill_color, outline=color, width=2)
            
            # 2. Coins renforcés
            len_corner = (x2 - x1) // 5
            draw.line([(x1, y1), (x1 + len_corner, y1)], fill=color, width=4)
            draw.line([(x1, y1), (x1, y1 + len_corner)], fill=color, width=4)
            
            # 3. Étiquette
            text = det['label']
            draw.rectangle([x1, y1-20, x1+100, y1], fill=(0,0,0,200))
            draw.text((x1+5, y1-18), text, fill="white", font=font)
            
        elif det['type'] == 'hand':
            # On ne dessine que si MediaPipe a été chargé correctement
            if mp_hands:
                # Dessiner le squelette de la main
                lms = det['landmarks']
                width, height = img.size
                
                # Connexions des doigts (simplifié)
                connections = mp_hands.HAND_CONNECTIONS
                points = {}
                for idx, lm in enumerate(lms.landmark):
                    px, py = int(lm.x * width), int(lm.y * height)
                    points[idx] = (px, py)
                    # Petit point bleu sur chaque articulation

                    draw.ellipse([px-3, py-3, px+3, py+3], fill="#00f2ff")
                
                # Lignes blanches entre les articulations
                for start_idx, end_idx in connections:
                    if start_idx in points and end_idx in points:
                        draw.line([points[start_idx], points[end_idx]], fill="white", width=2)
        
        elif det['type'] == 'pose':
            # Dessiner le squelette complet du corps (Toutes les parties du corps)
            if mp_pose:
                lms = det['landmarks']
                width, height = img.size
                points = {}
                for idx, lm in enumerate(lms.landmark):
                    if lm.visibility > 0.5: # On ne dessine que les parties visibles
                        px, py = int(lm.x * width), int(lm.y * height)
                        points[idx] = (px, py)
                        draw.ellipse([px-4, py-4, px+4, py+4], fill="#ff00f2") # Rose néon
                
                for start_idx, end_idx in mp_pose.POSE_CONNECTIONS:
                    if start_idx in points and end_idx in points:
                        draw.line([points[start_idx], points[end_idx]], fill="white", width=2)
        
        elif det['type'] == 'pose':
            # Dessiner le squelette complet du corps (Toutes les parties du corps)
            if mp_pose:
                lms = det['landmarks']
                width, height = img.size
                points = {}
                for idx, lm in enumerate(lms.landmark):
                    if lm.visibility > 0.5: # On ne dessine que les parties visibles
                        px, py = int(lm.x * width), int(lm.y * height)
                        points[idx] = (px, py)
                        draw.ellipse([px-4, py-4, px+4, py+4], fill="#ff00f2") # Rose néon
                
                for start_idx, end_idx in mp_pose.POSE_CONNECTIONS:
                    if start_idx in points and end_idx in points:
                        draw.line([points[start_idx], points[end_idx]], fill="white", width=2)

        elif det['type'] == 'path':
            # Dessine la trajectoire du geste
            pts = det['points']
            if len(pts) > 1:
                draw.line(pts, fill=det['color'], width=3)
                # Point final plus gros pour marquer le "bout" du bras
                last = pts[-1]
                draw.ellipse([last[0]-5, last[1]-5, last[0]+5, last[1]+5], fill="#00f2ff")
        
        elif det['type'] == 'vector':
            # Dessine le vecteur de force/interaction
            start = det['start']
            end = det['end']
            color = det['color']
            width_line = 4 if det['state'] == 'taken' else 2
            
            draw.line([start, end], fill=color, width=width_line)
            # Petit cercle sur l'objet
            draw.ellipse([end[0]-4, end[1]-4, end[0]+4, end[1]+4], fill=color, outline="white")
        
    return img


@app.get("/api/cameras")
async def get_active_cameras():
    """API pour récupérer la liste dynamique des caméras."""
    cameras = []
    for cam_id, data in CAMERA_FEEDS.items():
        cameras.append({
            "id": cam_id,
            "last_seen": data.get("last_seen", "..."),
            "person": CAMERA_USER_ASSIGNMENTS.get(cam_id, "Inconnu"),
            "person_count": data.get("person_count", 0),
            "objects_count": data.get("objects_count", "..."),
            "price": data.get("price", "...")
        })
    return cameras

# --- ROUTES DASHBOARD ADMIN ---

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard():
    mobile_url = (CLOUD_URL or NGROK_URL or f"https://{LOCAL_IP}:8000") + "/mobile"
    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <title>HYFLEX OBS - CONTROL ROOM</title>
        <meta charset="UTF-8">
        <style>
            body {{ background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
            
            /* Header style OBS */
            .menubar {{ background: #2b2b2b; padding: 5px 15px; border-bottom: 1px solid #444; display: flex; justify-content: space-between; align-items: center; height: 40px; }}
            .brand {{ font-weight: bold; color: #00f2ff; letter-spacing: 1px; }}
            .status {{ font-size: 0.8em; color: #00ff41; }}

            /* Layout principal */
            .main-container {{ flex: 1; display: flex; padding: 10px; gap: 10px; height: calc(100vh - 50px); }}
            
            /* Zone principale (Preview) */
            .preview-area {{ flex: 3; background: #000; border: 2px solid #00f2ff; position: relative; border-radius: 4px; overflow: hidden; }}
            .single-view {{ width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }}
            .preview-img {{ width: 100%; height: 100%; object-fit: contain; }}
            .preview-label {{ position: absolute; top: 10px; left: 10px; background: rgba(0,0,0,0.7); padding: 5px 10px; font-weight: bold; color: #fff; }}
            .top-controls {{ position: absolute; top: 10px; right: 10px; z-index: 100; display: flex; gap: 5px; }}
            .fs-btn {{ background: rgba(0,0,0,0.6); border: 1px solid #00f2ff; color: #00f2ff; padding: 5px 10px; cursor: pointer; width: auto; font-size: 0.8em; }}
            .fs-btn:hover {{ background: rgba(0, 242, 255, 0.2); }}
            
            /* Styles Grille */
            .grid-layout {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(45%, 1fr)); width: 100%; height: 100%; gap: 4px; background: #111; align-content: center; }}
            .grid-cell {{ position: relative; background: #000; border: 1px solid #333; overflow: hidden; display: flex; align-items: center; justify-content: center; aspect-ratio: 16/9; }}
            .grid-cell img {{ width: 100%; height: 100%; object-fit: contain; }}
            .grid-label {{ position: absolute; top: 5px; left: 5px; background: rgba(0,0,0,0.6); color: #00f2ff; padding: 2px 6px; font-size: 0.8em; font-weight: bold; }}

            /* État déconnecté */
            .grid-cell.offline {{ filter: grayscale(1) opacity(0.5); }}
            .grid-cell.offline::after {{ content: "CAMÉRA HORS-LIGNE"; position: absolute; color: #ff3333; font-weight: bold; font-size: 0.8em; }}

            /* Panneau latéral (Infos & Contrôles) */
            .side-panel {{ flex: 1; background: #1f1f1f; display: flex; flex-direction: column; gap: 10px; padding: 10px; border-radius: 4px; overflow-y: auto; }}
            .panel-box {{ background: #2b2b2b; padding: 10px; border-radius: 4px; border: 1px solid #3d3d3d; }}
            .panel-title {{ font-size: 0.9em; color: #00ff41; font-weight:bold; text-transform: uppercase; margin-bottom: 5px; border-bottom: 1px solid #444; padding-bottom: 3px; }}
            
            .settings-input {{ width: 100%; background: #16161a; border: 1px solid #444; color: #00f2ff; padding: 8px; border-radius: 4px; margin-bottom: 8px; font-size: 0.8em; }}
            .mode-toggle {{ display: flex; gap: 5px; margin-bottom: 10px; }}
            .mode-btn {{ flex: 1; padding: 5px; font-size: 0.7em; border: 1px solid #444; background: #222; color: #888; cursor: pointer; }}
            .mode-btn.active {{ background: #00f2ff; color: #000; border-color: #00f2ff; font-weight: bold; }}

            .qr-side {{ background: white; padding: 10px; border-radius: 4px; text-align: center; margin-top: 10px; }}
            /* Liste des scènes (Caméras) en bas */
            .scenes-container {{ height: 140px; background: #1a1a1a; display: flex; gap: 15px; padding: 15px; overflow-x: auto; border-top: 1px solid #444; align-items: center; }}
            .scene-card {{ min-width: 160px; height: 100px; background: #2b2b2b; border: 2px solid #444; position: relative; display: flex; flex-direction: column; }}
            .scene-thumb {{ flex: 1; background: #000; width: 100%; object-fit: cover; }}
            .scene-name {{ font-size: 0.8em; padding: 5px; text-align: center; background: #222; }}
        </style>
    </head>
    <body>
        <div class="menubar">
            <div class="brand">HYFLEX CONTROL ROOM</div>
            <div class="status">REC [ACTIVE] | CAMERAS: 5 | CPU: 14% | CLOUD: CONNECTED</div>
        </div>
        
        <div class="main-container">
            <!-- Grande vue principale (La première caméra ou celle sélectionnée) -->
            <div class="preview-area" id="preview-container">
                <div class="preview-label">PROGRAM</div>
                <div class="top-controls">
                    <button class="fs-btn" onclick="toggleFullscreen()">FULLSCREEN</button>
                </div>
                <div id="grid-view" class="grid-layout">
                    <div style="color:#666; display:flex; align-items:center; justify-content:center; grid-column:1/-1; width:100%; height:100%;">EN ATTENTE DE FLUX...</div>
                </div>
            </div>

            <!-- Panneau de droite -->
            <div class="side-panel">
                <div class="panel-box">
                    <div class="panel-title">LIVE STATUS</div>
                    <div id="info-display" style="font-size: 0.9em; color: #ccc;">
                        <div class="panel-box" style="border:none; padding:0; background:none;">
                            <div class="panel-title" style="font-size:0.8em; color:#aaa; text-align:center;">COMPTEUR VISAGES</div>
                            <div id="big-counter" style="font-size: 3.5em; color: #00f2ff; text-align: center; font-weight: bold; margin: 10px 0;">0</div>
                            <button onclick="triggerCleaning()" style="width:100%; padding:10px; background:#222; color:#fff; border:1px solid #444; border-radius:4px; cursor:pointer; font-weight:bold; text-transform:uppercase; transition:0.2s;">MODE NETTOYAGE</button>
                            <button onclick="location.href='/register_product'" style="width:100%; padding:10px; background:#00f2ff; color:#000; border:none; border-radius:4px; cursor:pointer; font-weight:bold; text-transform:uppercase; margin-top:5px;">MODE TRAINING</button>
                        </div>

                        Système actif.<br>
                        IA: YOLO + MediaPipe<br>
                        Mode: Surveillance
                    </div>
                </div>

                <div class="panel-box">
                    <div class="panel-title">PAYDUNYA CONFIG</div>
                    <div class="mode-toggle">
                        <button id="mode-test" class="mode-btn active" onclick="setPayMode('test')">SANDBOX</button>
                        <button id="mode-live" class="mode-btn" onclick="setPayMode('live')">LIVE</button>
                    </div>
                    <input type="password" id="pd-master" class="settings-input" placeholder="Master Key">
                    <input type="password" id="pd-private" class="settings-input" placeholder="Private Key">
                    <input type="password" id="pd-public" class="settings-input" placeholder="Public Key">
                    <input type="password" id="pd-token" class="settings-input" placeholder="Token">
                    <button onclick="savePaySettings()" class="fs-btn" style="width:100%; margin-bottom:5px;">ENREGISTRER CLES</button>
                    <button onclick="triggerSetup()" class="fs-btn" style="width:100%; border-color: #ff9900; color: #ff9900;">INITIALISER DB (SETUP)</button>
                </div>

                <div class="panel-box">
                    <div class="panel-title">GESTION DATA</div>
                    <a href="/api/export_transactions" class="fs-btn" style="text-decoration:none; background:#ff9900; color:black; display:block; text-align:center; margin-bottom:10px; font-weight:bold;">EXPORTER CSV</a>
                    <button onclick="triggerCleaning()" style="width:100%; padding:8px; background:#444; color:#fff; border:none; cursor:pointer; margin-bottom:10px;">CLEAR TRACKING</button>
                    <button onclick="location.href='/register_product'" style="width:100%; padding:10px; background:#00f2ff; color:#000; border:none; border-radius:4px; cursor:pointer; font-weight:bold; text-transform:uppercase;">MODE TRAINING</button>
                </div>

                <div class="panel-box">
                    <div class="panel-title">ACCÈS RAPIDES</div>
                    <a href="/manager" style="color: #ff9900; text-decoration: none; display:block; padding:5px; border-bottom:1px solid #333;">MANAGER</a>
                    <a href="/client" style="color: #00f2ff; text-decoration: none; display:block; padding:5px;">CLIENT WALLET</a>
                </div>

                <div class="panel-box">
                    <div class="panel-title">CONNECT MOBILE</div>
                    <div class="qr-side"><img src="https://api.qrserver.com/v1/create-qr-code/?size=120x120&data={mobile_url}" width="120"></div>
                    <p style="font-size:0.7em; color:#888; text-align:center; margin-top:5px;">Scannez pour ajouter une caméra</p>
                </div>
            </div>
        </div>

        <!-- Barre des scènes (Caméras) -->
        <div class="scenes-container" id="scenes-list">
            <div style='color:#666; padding: 20px;' id="waiting-msg">CHARGEMENT...</div>
        </div>

        <!-- PANNEAU PROFIL RFID (apparaît au scan) -->
        <div id="rfid-panel" style="display:none; position:fixed; top:60px; right:20px; z-index:1000;
             background:#1a1a2e; border:2px solid #00f2ff; border-radius:16px; padding:20px; width:230px;
             box-shadow:0 0 30px rgba(0,242,255,0.4); animation:slideIn 0.3s ease;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <span style="color:#00f2ff; font-weight:bold; font-size:0.85em; letter-spacing:1px;">BADGE DETECTE</span>
                <span onclick="document.getElementById('rfid-panel').style.display='none'"
                      style="color:#666; cursor:pointer; font-size:1.2em;">✕</span>
            </div>
            <img id="rfid-photo" src="" width="80" height="80"
                 style="border-radius:50%; border:2px solid #00f2ff; display:block; margin:0 auto 12px; object-fit:cover;">
            <div id="rfid-name" style="text-align:center; font-size:1.1em; font-weight:bold; color:#fff; margin-bottom:4px;"></div>
            <div id="rfid-uid" style="text-align:center; font-size:0.7em; color:#555; margin-bottom:12px;"></div>
            <div style="background:#0d0d1a; border-radius:8px; padding:10px; text-align:center;">
                <div style="color:#888; font-size:0.7em; margin-bottom:2px;">SOLDE WALLET</div>
                <div id="rfid-balance" style="color:#00ff41; font-size:1.4em; font-weight:bold;"></div>
            </div>
            <div style="margin-top:10px; text-align:center;">
                <span style="background:#00ff41; color:#000; padding:4px 12px; border-radius:20px;
                      font-size:0.75em; font-weight:bold;">✓ ACCES AUTORISE</span>
            </div>
        </div>

        <script>
            const APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxxSOZyptRBlGr0svsXlWzjANkMK8RRz03gVizG56nS6KsIfyVW0ghuyxonCY7ebqYGjQ/exec";
            let currentPayMode = 'test';

            // Charger les paramètres au démarrage
            async function loadSettings() {{
                try {{
                    const res = await fetch(APPS_SCRIPT_URL, {{
                        method: 'POST',
                        body: JSON.stringify({{ action: 'getSettings' }})
                    }});
                    const data = await res.json();
                    if(data.success) {{
                        document.getElementById('pd-master').value = data.settings.masterKey;
                        document.getElementById('pd-private').value = data.settings.privateKey;
                        document.getElementById('pd-public').value = data.settings.publicKey;
                        document.getElementById('pd-token').value = data.settings.token;
                        setPayMode(data.settings.mode);
                    }}
                }} catch(e) {{ console.error("Erreur chargement settings"); }}
            }}

            function setPayMode(mode) {{
                currentPayMode = mode;
                document.getElementById('mode-test').className = mode === 'test' ? 'mode-btn active' : 'mode-btn';
                document.getElementById('mode-live').className = mode === 'live' ? 'mode-btn active' : 'mode-btn';
            }}

            async function savePaySettings() {{
                const payload = {{
                    action: 'saveSettings',
                    payload: {{
                        masterKey: document.getElementById('pd-master').value,
                        privateKey: document.getElementById('pd-private').value,
                        publicKey: document.getElementById('pd-public').value,
                        token: document.getElementById('pd-token').value,
                        mode: currentPayMode
                    }}
                }};
                try {{
                    await fetch(APPS_SCRIPT_URL, {{ method: 'POST', body: JSON.stringify(payload) }});
                    alert("✅ Paramètres PayDunya mis à jour sur Google Apps Script !");
                }} catch(e) {{ alert("❌ Erreur de sauvegarde"); }}
            }}

            async function triggerSetup() {{
                if(confirm("Initialiser la base de données Google Sheets ?")) {{
                    window.open(APPS_SCRIPT_URL.replace('/exec', '') + '/exec', '_blank');
                }}
            }}

            window.onload = loadSettings;

            // Nouvelle fonction pour assigner manuellement sans photo
            async function assignUserToCamera() {{
                const name = document.getElementById('reg-name').value;
                // On récupère la caméra actuellement sélectionnée ou visible
                // Pour simplifier, on prend la première caméra active ou on demande à l'utilisateur de cliquer sur une cam
                // Ici, on va supposer que l'utilisateur tape le nom de la caméra dans un prompt s'il n'y a pas de sélection active claire dans le code JS actuel
                // Ou mieux : on assigne à TOUTES les caméras actives pour le test
                
                if(!name) {{ alert("Entrez un nom !"); return; }}
                
                // On envoie une requête pour assigner ce nom à la caméra courante (stockée côté serveur ou client)
                // Pour faire simple ici, on va créer un endpoint simple
                const formData = new FormData();
                formData.append('user_id', name);
                
                try {{
                    await fetch('/api/manual_assign', {{ method: 'POST', body: formData }});
                    document.getElementById('reg-status').innerHTML = "✅ Client " + name + " connecté !";
                    document.getElementById('reg-name').value = "";
                }} catch(e) {{
                    alert("Erreur connectivité");
                }}
            }}

            async function registerFace() {{
                const name = document.getElementById('reg-name').value;
                const fileInput = document.getElementById('reg-file');
                const statusDiv = document.getElementById('reg-status');
                
                if(!name || fileInput.files.length === 0) {{
                    statusDiv.innerHTML = "⚠️ Nom et photo requis.";
                    return;
                }}
                
                const formData = new FormData();
                formData.append('user_id', name);
                formData.append('file', fileInput.files[0]);
                
                statusDiv.innerHTML = "⏳ Envoi...";
                
                try {{
                    const res = await fetch('/api/register_face', {{ method: 'POST', body: formData }});
                    const data = await res.json();
                    if(data.status === 'success') {{
                        statusDiv.innerHTML = "✅ Visage appris !";
                        document.getElementById('face-form').reset();
                    }} else {{
                        statusDiv.innerHTML = "❌ Erreur: " + (data.error || "Inconnue");
                    }}
                }} catch(e) {{
                    statusDiv.innerHTML = "❌ Erreur réseau";
                }}
            }}

            async function triggerCleaning() {{
                if(confirm("Confirmer le NETTOYAGE du système ? (Reset compteurs & tracking)")) {{
                    try {{
                        await fetch('/api/clean_reset', {{ method: 'POST' }});
                        alert("Système nettoyé !");
                    }} catch(e) {{
                        alert("Erreur nettoyage");
                    }}
                }}
            }}

            let activeSockets = {{}}; // Stocke les WebSockets actifs par caméra ID

            function toggleFullscreen() {{
                const elem = document.getElementById('preview-container');
                if (!document.fullscreenElement) {{
                    elem.requestFullscreen().catch(err => {{
                        console.log(`Erreur plein écran: ${{err.message}}`);
                    }});
                }} else {{
                    document.exitFullscreen();
                }}
            }}

            // Met à jour la grille de caméras
            async function updateGrid() {{                
                const gridContainer = document.getElementById('grid-view');
                const res = await fetch('/api/cameras');
                const cameras = await res.json();
                
                let totalPeople = 0;

                // Si aucune caméra
                if (cameras.length === 0) {{
                    if (!gridContainer.innerHTML.includes('EN ATTENTE')) {{
                         gridContainer.innerHTML = '<div style="color:#666; display:flex; align-items:center; justify-content:center; grid-column:1/-1; width:100%; height:100%;">EN ATTENTE DE FLUX...</div>';
                    }}
                    return;
                }} else {{
                    // Supprimer le message d'attente s'il existe
                    const waitMsg = gridContainer.querySelector('div[style*="color:#666"]');
                    if (waitMsg) waitMsg.remove();
                }}

                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';

                // 1. AJOUT DES NOUVELLES CAMÉRAS
                cameras.forEach(cam => {{
                    totalPeople += cam.person_count || 0;

                    if(!document.getElementById('grid-cell-' + cam.id)) {{
                        const cell = document.createElement('div');
                        cell.className = 'grid-cell';
                        cell.id = 'grid-cell-' + cam.id;
                        cell.innerHTML = `<div class="grid-label">${{cam.id}} | Pers: <span id="count-${{cam.id}}">${{cam.person_count}}</span></div><img id="grid-img-${{cam.id}}">`;
                        gridContainer.appendChild(cell);

                        // Connexion WebSocket pour cette caméra
                        const ws = new WebSocket(protocol + window.location.host + "/ws_view/" + cam.id);
                        ws.binaryType = "blob";
                        ws.onmessage = (e) => {{
                            const img = document.getElementById('grid-img-' + cam.id);
                            const cell = document.getElementById('grid-cell-' + cam.id);
                            if(img) {{
                                if(cell) cell.classList.remove('offline');
                                if (img.dataset.lastUrl) URL.revokeObjectURL(img.dataset.lastUrl);
                                const url = URL.createObjectURL(e.data);
                                img.src = url;
                                img.dataset.lastUrl = url;
                            }}
                        }};
                        activeSockets[cam.id] = ws;
                    }} else {{
                        // Mise à jour du compteur sur la cellule existante
                        document.getElementById('count-' + cam.id).innerText = cam.person_count;
                    }}
                }});

                // Mise à jour du GROS COMPTEUR
                document.getElementById('big-counter').innerText = totalPeople;

                // 2. SUPPRESSION DES CAMÉRAS DÉCONNECTÉES
                const activeIds = cameras.map(c => c.id);
                const cells = document.querySelectorAll('.grid-cell');
                
                cells.forEach(cell => {{
                    const id = cell.id.replace('grid-cell-', '');
                    if (!activeIds.includes(id)) {{
                        // Fermeture du WebSocket
                        if (activeSockets[id]) {{
                            activeSockets[id].close();
                            delete activeSockets[id];
                        }}
                        // Suppression de l'élément HTML
                        cell.remove();
                    }}
                }});
            }}

            async function refreshLoop() {{
                // Rafraichir les vignettes du bas
                const thumbs = document.querySelectorAll('.scene-thumb');
                thumbs.forEach(img => {{
                    img.src = img.src.split('?')[0] + '?t=' + new Date().getTime();
                }});

                // Mise à jour de la liste des caméras ET de la grille principale
                await updateCameraList();
                await updateGrid();
                
                setTimeout(refreshLoop, 1000); // Boucle plus lente car la vidéo principale est gérée par WebSocket
            }}

            async function updateCameraList() {{
                try {{
                    const res = await fetch('/api/cameras');
                    const cameras = await res.json();
                    const container = document.getElementById('scenes-list');
                    
                    if(cameras.length === 0) {{
                        if(!container.innerHTML.includes('EN ATTENTE')) {{
                             container.innerHTML = "<div style='color:#666; padding: 20px;'>EN ATTENTE DE CONNEXION MOBILE...</div>";
                        }}
                        return;
                    }}

                    // Nettoyage du message d'attente
                    if(container.querySelector('div[style*="color:#666"]')) container.innerHTML = '';

                    // 1. AJOUT DES NOUVELLES CAMÉRAS
                    cameras.forEach(cam => {{
                        if(!document.getElementById('card-' + cam.id)) {{
                            const div = document.createElement('div');
                            div.className = 'scene-card';
                            div.id = 'card-' + cam.id;
                            div.innerHTML = `<img src="/video_feed/${{cam.id}}" class="scene-thumb"><div class="scene-name">CAM ${{cam.id}}</div>`;
                            container.appendChild(div);
                        }}
                    }});

                    // 2. SUPPRESSION DES ANCIENNES
                    const activeIds = cameras.map(c => 'card-' + c.id);
                    document.querySelectorAll('.scene-card').forEach(card => {{
                        if(!activeIds.includes(card.id)) card.remove();
                    }});

                }} catch(e) {{
                    console.error("Erreur API:", e);
                }}
            }}
            
            refreshLoop();

            // ── POLLING RFID PROFIL (toutes les 2 secondes) ──
            let lastRfidTs = 0;
            async function pollRfid() {{
                try {{
                    const res = await fetch('/api/last_rfid_event');
                    const ev = await res.json();
                    if (ev.timestamp && ev.timestamp !== lastRfidTs && ev.user) {{
                        lastRfidTs = ev.timestamp;
                        document.getElementById('rfid-name').innerText = ev.user;
                        document.getElementById('rfid-uid').innerText = 'UID: ' + ev.uid;
                        document.getElementById('rfid-balance').innerText = ev.balance.toLocaleString() + ' FCFA';
                        document.getElementById('rfid-photo').src = ev.photo_url || '';
                        document.getElementById('rfid-panel').style.display = 'block';
                        // Fermeture auto après 15 secondes
                        setTimeout(() => {{ document.getElementById('rfid-panel').style.display = 'none'; }}, 15000);
                    }}
                }} catch(e) {{}}
                setTimeout(pollRfid, 2000);
            }}
            pollRfid();
        </script>
    </body>
    </html>
    """
    return html


@app.get("/video_feed/{camera_id}")
async def get_video_feed(camera_id: str):
    """Renvoie la dernière image traitée (avec dessins) pour le dashboard."""
    if camera_id in LATEST_FRAME_BYTES:
        try:
            # 1. Récupérer l'image brute
            img_bytes = LATEST_FRAME_BYTES[camera_id]
            img = Image.open(io.BytesIO(img_bytes))
            
            # 2. Dessiner les dernières détections connues (IA asynchrone)
            detections = LAST_DETECTIONS.get(camera_id, [])
            img = draw_hud(img, detections)
            
            # 3. Convertir pour l'affichage
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="image/jpeg")
        except:
            return StreamingResponse(io.BytesIO(b''), media_type="image/jpeg")
    else:
        # Image vide si pas de flux
        return StreamingResponse(io.BytesIO(b''), media_type="image/jpeg")

@app.get("/manager", response_class=HTMLResponse)
async def manager_dashboard():
    """Interface Manager pour enregistrer des produits."""
    # Génération de la liste des produits
    products_html = ""
    for name, price in DB_PRODUITS.items():
        products_html += f"<tr><td>{name.capitalize()}</td><td>{price} FCFA</td></tr>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>HYFLEX - MANAGER</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ background: #111; color: #eee; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            h1 {{ color: #ff9900; border-bottom: 2px solid #ff9900; padding-bottom: 10px; }}
            .card {{ background: #222; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #333; }}
            input, button {{ width: 100%; padding: 12px; margin: 8px 0; border-radius: 4px; border: none; box-sizing: border-box; }}
            input {{ background: #333; color: white; border: 1px solid #555; }}
            input:focus {{ border-color: #ff9900; outline: none; }}
            button {{ background: #ff9900; color: black; font-weight: bold; cursor: pointer; font-size: 1.1em; }}
            button:hover {{ background: #ffaa33; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #444; }}
            th {{ color: #ff9900; }}
            .back-btn {{ background: #444; color: white; width: auto; padding: 10px 20px; text-decoration: none; display: inline-block; text-align: center; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">⬅ Retour Hub</a>
            <h1>🛠️ MANAGER STUDIO</h1>
            
            <div class="card">
                <h2 style="margin-top:0">ENREGISTRER UN PRODUIT</h2>
                <p style="color:#aaa; font-size:0.9em;">Ajoutez un produit à la base de données. Le nom doit correspondre à la classe détectée (ex: 'bottle').</p>
                <a href="/register_product" style="display:block; background:#00f2ff; color:black; text-align:center; padding:10px; border-radius:4px; text-decoration:none; font-weight:bold; margin-bottom:15px;">SCANNER PRODUIT 360° (DATASET)</a>
                <form action="/add_product_action" method="post">
                    <input type="text" name="product_name" placeholder="Nom du produit (ex: coca)" required>
                    <input type="number" name="price" placeholder="Prix (FCFA)" required>
                    <button type="submit">ENREGISTRER PRODUIT</button>
                </form>
            </div>

            <div class="card">
                <h2 style="margin-top:0">📋 BASE DE DONNÉES</h2>
                <table>
                    <thead><tr><th>NOM</th><th>PRIX</th></tr></thead>
                    <tbody>
                        {products_html}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.get("/register_product", response_class=HTMLResponse)
async def register_product_interface():
    """Interface pour scanner un produit sous tous ses angles."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
    <title>HYFLEX - PRODUIT 360°</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { background: #050505; color: #fff; font-family: 'Segoe UI', sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
        .container { width: 90%; max-width: 400px; background: #111; padding: 25px; border: 1px solid #333; border-radius: 12px; border: 2px solid #ff9900; text-align: center; box-shadow: 0 0 30px rgba(255, 153, 0, 0.2); }
        h1 { color: #ff9900; margin-bottom: 20px; font-size: 1.6em; text-transform: uppercase; letter-spacing: 2px; font-weight: 800; }
        input { width: 100%; padding: 15px; margin: 10px 0; background: #222; border: 1px solid #444; color: white; border-radius: 8px; box-sizing: border-box; font-size: 1.1em; text-align: center; }
        input:focus { border-color: #ff9900; outline: none; }
        #video-box { width: 100%; height: 320px; background: #000; border: 2px solid #333; margin-bottom: 20px; position: relative; overflow: hidden; border-radius: 8px; }
        video { width: 100%; height: 100%; object-fit: cover; }
        .btn { background: #ff9900; color: #000; border: none; padding: 15px; width: 100%; font-weight: bold; font-size: 1.2em; border-radius: 8px; cursor: pointer; text-transform: uppercase; transition: 0.3s; margin-top: 10px; display: block; }
        .guide-overlay { position: absolute; top: 10px; left: 10px; background: rgba(0,0,0,0.7); padding: 5px 10px; border-radius: 4px; color: #ff9900; font-weight: bold; pointer-events: none; }
        .progress-bar { width: 100%; height: 5px; background: #333; margin-top: 10px; border-radius: 3px; overflow: hidden; }
        .progress-fill { height: 100%; background: #ff9900; width: 0%; transition: width 0.3s; }
        .status { margin-top: 20px; color: #aaa; }
    </style>
    </head>
    <body>
        <div class="container">
            <h1>📦 SCAN PRODUIT</h1>
            <div id="video-box">
                <video id="vid" autoplay muted playsinline></video>
                <div class="guide-overlay" id="guide-text">Étape 1/5 : FACE AVANT</div>
            </div>
            <div class="progress-bar"><div class="progress-fill" id="progress"></div></div>
            
            <input type="text" id="prod_name" placeholder="NOM DU PRODUIT (ex: coca)" autocomplete="off">
            <input type="number" id="prod_price" placeholder="PRIX (FCFA)" autocomplete="off">
            <button class="btn" id="btn-action" onclick="startSequence()">COMMENCER SCAN</button>
            <div class="status" id="status">Prêt.</div>
        </div>
        <canvas id="cvs" style="display:none"></canvas>
        <script>
            const video = document.getElementById('vid');
            const canvas = document.getElementById('cvs');
            const status = document.getElementById('status');
            const guideText = document.getElementById('guide-text');
            const progress = document.getElementById('progress');
            const btn = document.getElementById('btn-action');
            
            navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
            .then(stream => video.srcObject = stream);

            const steps = [
                { pose: "front", text: "Vue de FACE" },
                { pose: "back", text: "Vue ARRIERE" },
                { pose: "left", text: "Cote GAUCHE" },
                { pose: "right", text: "Cote DROIT" },
                { pose: "top", text: "Vue de DESSUS" }
            ];
            let currentStep = 0;

            async function startSequence() {
                const name = document.getElementById('prod_name').value;
                const price = document.getElementById('prod_price').value;
                if(!name || !price) { status.innerText = "⚠️ Remplissez nom et prix !"; return; }
                
                document.getElementById('prod_name').disabled = true;
                document.getElementById('prod_price').disabled = true;
                btn.onclick = captureStep;
                currentStep = 0;
                updateUI();
            }

            function updateUI() {
                if (currentStep >= steps.length) {
                    status.innerHTML = "✅ PRODUIT ENREGISTRÉ !";
                    guideText.innerText = "TERMINÉ";
                    btn.style.display = "none";
                    setTimeout(() => window.location.href='/manager', 2000);
                    return;
                }
                const step = steps[currentStep];
                guideText.innerText = `Étape ${currentStep + 1}/5 : ${step.text}`;
                btn.innerText = "CAPTURER";
                progress.style.width = ((currentStep / steps.length) * 100) + "%";
            }

            async function captureStep() {
                const name = document.getElementById('prod_name').value;
                const price = document.getElementById('prod_price').value;
                const step = steps[currentStep];
                status.innerHTML = "⏳ Envoi...";
                
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0);
                
                canvas.toBlob(async (blob) => {
                    const formData = new FormData();
                    formData.append('product_name', name);
                    formData.append('price', price);
                    formData.append('pose', step.pose);
                    formData.append('file', blob, name + '_' + step.pose + '.jpg');
                    
                    try {
                        await fetch('/api/signup_product', { method: 'POST', body: formData });
                        currentStep++;
                        updateUI();
                        status.innerHTML = "Image OK.";
                    } catch(e) {
                        status.innerHTML = "❌ Erreur envoi";
                    }
                }, 'image/jpeg', 0.8);
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/api/signup_product")
async def signup_product(product_name: str = Form(...), price: str = Form(...), pose: str = Form(...), file: UploadFile = File(...)):
    """Enregistre une image produit et l'envoie au Cloud."""
    content = await file.read()
    
    # 1. Sauvegarde Locale
    folder = "produits_dataset"
    if not os.path.exists(folder): os.makedirs(folder)
    
    with open(os.path.join(folder, f"{product_name}_{pose}.jpg"), "wb") as f: # Sauvegarde synchrone rapide
        f.write(content)
    
    # 2. Envoi Cloud
    t = threading.Thread(target=send_image_to_google, args=(f"PROD_{product_name}_{pose}.jpg", content))
    t.start()
    
    # 3. Enregistrement Base de données (Si c'est la vue de face)
    if pose == "front":
        add_product_to_google(product_name, price)
        
    # 4. Apprentissage instantané local
    load_known_products(force_reload=True)
        
    return {"status": "ok"}

class ProductRequest(BaseModel):
    product_name: str
    price: int


@app.post("/add_product_action")
async def add_product_action(request: Request):
    """Reçoit le formulaire d'ajout depuis le dashboard."""
    form = await request.form()
    name = form.get("product_name")
    price = form.get("price")
    

    if name and price:
        print(f"Enregistrement manuel Dashboard : {name} -> {price} FCFA")
        add_product_to_google(name, price)
        return RedirectResponse(url="/manager", status_code=303) # Retour au manager
    return {"error": "Données manquantes"}


@app.post("/api/manual_assign")
async def manual_assign_user(user_id: str = Form(...)):
    """Assigne un utilisateur à toutes les caméras actives (Mode dégradé sans IA)."""
    for cam_id in CAMERA_FEEDS.keys():
        CAMERA_USER_ASSIGNMENTS[cam_id] = user_id
    
    # On s'assure que le wallet existe
    if user_id not in WALLETS:
        WALLETS[user_id] = 5000
        save_wallets()
    return {"status": "assigned", "user": user_id}

@app.post("/api/register_face")
async def register_face(user_id: str = Form(...), file: UploadFile = File(...)):
    """Enregistre un nouveau visage et recharge le modèle."""
    if not FACE_REC_AVAILABLE:
        return {"error": "Module de reconnaissance faciale non actif"}
    
    folder = "visages"
    if not os.path.exists(folder): os.makedirs(folder)
    
    # Sauvegarde de l'image
    file_path = os.path.join(folder, f"{user_id}.jpg")
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
        
    if FACE_REC_AVAILABLE:
        await asyncio.to_thread(load_known_faces)
    
    threading.Thread(target=send_image_to_google, args=(f"FACE_{user_id}.jpg", content), daemon=True).start()
    
    if user_id not in WALLETS:
        WALLETS[user_id] = 5000
        save_wallets()
        
    return {"status": "success", "user_id": user_id}


# --- WEBSOCKET POUR FLUX VIDÉO ULTRA-RAPIDE ---

@app.websocket("/ws_view/{camera_id}")
async def websocket_view_endpoint(websocket: WebSocket, camera_id: str):
    """Endpoint WebSocket pour envoyer le flux vidéo à l'Admin."""
    await websocket.accept()
    try:
        while True:
            if camera_id in LATEST_FRAME_BYTES:
                # On recrée l'image HUD à la volée pour l'admin
                # C'est ici qu'on fusionne l'image fluide et les carrés de l'IA
                try:
                    img_bytes = LATEST_FRAME_BYTES[camera_id]
                    img = Image.open(io.BytesIO(img_bytes))
                    detections = LAST_DETECTIONS.get(camera_id, [])
                    img = draw_hud(img, detections)
                    
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=50, optimize=False)
                    await websocket.send_bytes(buf.getvalue())
                except:
                    pass
            await asyncio.sleep(0.08) # ~12 FPS pour l'admin (économise le CPU)
    except Exception:
        pass # Déconnexion normale

@app.websocket("/ws/{camera_id}")
async def websocket_endpoint(websocket: WebSocket, camera_id: str):
    """
    RÉCEPTION PURE ET DURE.
    Ce endpoint ne fait plus AUCUN traitement. Il ne fait que recevoir.
    Résultat : Fluidité maximale sur le mobile.
    """
    await websocket.accept()

    try:
        while True:
            # Réception du flux binaire en continu (Zéro latence HTTP)
            contents = await websocket.receive_bytes()
            
            # STOCKAGE IMMÉDIAT (Le thread d'IA viendra piocher ici)
            LATEST_FRAME_BYTES[camera_id] = contents
            
            # Mise à jour minimale des infos pour l'API
            detections = LAST_DETECTIONS.get(camera_id, [])
            detected_info = f"{len(detections)} objets"

            # Mise à jour de la mémoire partagée pour le dashboard Admin
            CAMERA_FEEDS.setdefault(camera_id, {}).update({
                # On ne stocke plus l'image traitée ici pour gagner du temps
                # L'admin la génèrera lui-même
                "last_seen": datetime.datetime.now().strftime("%H:%M:%S"),
                "objects_count": detected_info, # Affiche les objets détectés
                "price": "-",
                "last_analysis_ts": 0
            })
            
            # Pas de réponse envoyée au client pour maximiser la bande passante montante
            
    except (WebSocketDisconnect, ConnectionResetError):
        print(f"Caméra {camera_id} déconnectée.")
        if camera_id in CAMERA_FEEDS:
            del CAMERA_FEEDS[camera_id]
    except Exception as e:
        print(f"Erreur WebSocket: {e}")


@app.post("/detect/{camera_id}")
async def detect_merchandise(camera_id: str, file: UploadFile = File(...)):
    """
    Reçoit une image, identifie la personne et l'objet, et enregistre la transaction via l'API Google.
    """
    try:
        # Lire le fichier image
        contents = await file.read()
        
        # --- MODE FLUX VIDÉO ULTRA-RAPIDE (SANS IA) ---
        # On ne fait plus d'analyse Groq pour l'instant pour privilégier la fluidité
        # --- MODE INTELLIGENT ---
        if MODEL:
            img_pil = Image.open(io.BytesIO(contents))
            detections = process_pick_and_go_logic(camera_id, img_pil)
            img_pil = draw_hud(img_pil, detections)
            buf = io.BytesIO()
            img_pil.save(buf, format="JPEG")
            processed_image = buf.getvalue()
            info = f"Scan OK: {len(detections)}"
        else:
            info_overlay = [f"CAM: {camera_id}", "IA NON CHARGÉE"]
            processed_image = draw_overlays(contents, info_overlay)
            info = "No AI"
        
        # 5. GÉNÉRATION DE L'IMAGE POUR LE DASHBOARD ADMIN (AVEC DESSINS)
        info_overlay = [
            f"CAM: {camera_id}",
            f"STATUS: EN LIGNE",
        ]
        processed_image = draw_overlays(contents, info_overlay)
        
        # Mise à jour directe de la mémoire vidéo
        CAMERA_FEEDS.setdefault(camera_id, {}).update({
            "image_bytes": processed_image,
            "last_seen": "Video Direct",
            "objects_count": info,
            "price": "-",
            "last_analysis_ts": 0
        })
        
        return {"status": "ok"}

    except Exception as e:
        print(f"❌ ERREUR : {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/mobile", response_class=HTMLResponse)
async def mobile_interface():
    """
    Interface web de secours pour utiliser la caméra du smartphone.
    Accessible via http://<VOTRE_IP>:8000/mobile
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>JEL DEM - SHOP & GO</title>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <style>
            body { margin: 0; background: #000; color: white; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; }
            #video-container { position: relative; flex: 1; overflow: hidden; display: flex; align-items: center; justify-content: center; background: #111; }
            video { width: 100%; height: 100%; object-fit: cover; }
            #overlay { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.7); padding: 20px; font-size: 16px; min-height: 80px; transition: 0.3s; z-index: 2; border-top: 1px solid #444; }
            #brand-overlay { position: absolute; top: 20px; left: 20px; z-index: 2; font-weight: bold; text-shadow: 0 2px 4px rgba(0,0,0,0.8); letter-spacing: 1px; }
            .controls { padding: 15px; background: #222; text-align: center; z-index: 3; display: flex; gap: 10px; justify-content: center; }
            button { flex: 1; background: #00f2ff; color: #000; border: none; padding: 15px; font-size: 14px; border-radius: 30px; cursor: pointer; font-weight: bold; box-shadow: 0 0 15px rgba(0, 242, 255, 0.4); text-transform: uppercase; }
            button.stop { background: #dc3545; }
            #status { font-size: 12px; color: #aaa; margin-bottom: 5px; }
            .blink { animation: blinker 1s linear infinite; color: #0f0; }
            @keyframes blinker { 50% { opacity: 0; } }
        </style>
    </head>
    <body>
        <div id="video-container">
            <div id="brand-overlay">JEL <span style="color:#f97316;">DEM</span><br><span style="color:#00f2ff; font-size:0.8em;">SHOP & GO</span></div>
            <video id="vid" autoplay playsinline muted></video>
            <div id="overlay">
                <div id="status">Prêt</div>
                <div id="result">Appuyez sur Démarrer pour voir le tapis en direct.</div>
            </div>
        </div>
        <div class="controls">
            <button id="btn" onclick="toggleLive()">🔴 Démarrer le Live</button>
        </div>
        <canvas id="cvs" style="display:none"></canvas>
        <script>
            let isStreaming = false;
            // Génération d'un ID unique pour ce téléphone (ex: cam_1234)
            const clientId = "cam_" + Math.floor(Math.random() * 8999 + 1000);
            const video = document.getElementById('vid');
            const canvas = document.getElementById('cvs');
            const resultDiv = document.getElementById('result');
            const statusDiv = document.getElementById('status');
            const btn = document.getElementById('btn');
            let ws = null;

            async function toggleLive() {
                if (isStreaming) {
                    isStreaming = false;
                    if (ws) { ws.close(); ws = null; }
                    btn.textContent = "Demarrer le Live";
                    btn.className = "";
                    statusDiv.innerHTML = "Pause";
                    return;
                }

                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ 
                        video: { facingMode: "environment" } 
                    });
                    video.srcObject = stream;
                    
                    btn.textContent = "Arreter";
                    btn.className = "stop";
                    
                    // Connexion WebSocket (Le tuyau rapide)
                    const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                    const wsUrl = protocol + window.location.host + "/ws/" + clientId;
                    
                    ws = new WebSocket(wsUrl);
                    
                    ws.onopen = () => {
                        statusDiv.innerHTML = "<span class='blink'>●</span> ID: " + clientId + " - CONNECTÉ (WS)";
                        isStreaming = true;
                        capture();
                    };
                    
                    ws.onclose = () => {
                        statusDiv.innerHTML = "Déconnecté";
                        isStreaming = false;
                        btn.textContent = "🔴 Démarrer le Live";
                        btn.className = "";
                    };
                    
                    ws.onerror = (err) => {
                        statusDiv.innerHTML = "Erreur Connection";
                        console.error(err);
                    };

                } catch (e) {
                    if (location.protocol !== 'https:') {
                        alert("⚠️ SÉCURITÉ NAVIGATEUR ⚠️\\n\\nChrome bloque la caméra car le site est en HTTP.\\n\\nSOLUTION SUR TÉLÉPHONE :\\n1. Allez sur : chrome://flags\\n2. Cherchez : 'insecure origin'\\n3. Activez l'option et ajoutez : " + location.origin + "\\n4. Relancez Chrome.");
                    } else {
                        alert("Erreur technique : " + e);
                    }
                }
            }

            async function capture() {
                if (!isStreaming || !ws || ws.readyState !== WebSocket.OPEN) return;
                if (!video.videoWidth) return;
                
                // AMÉLIORATION DISTANCE: On augmente la résolution envoyée (720p)
                const maxH = 720; 
                let w = video.videoWidth;
                let h = video.videoHeight;
                if (h > maxH) {
                    w = Math.floor(w * (maxH / h));
                    h = maxH;
                }
                
                canvas.width = w;
                canvas.height = h;
                canvas.getContext('2d').drawImage(video, 0, 0, w, h);
                
                // Compression JPEG (0.3 = 30% qualité, suffisant pour la surveillance et très rapide)
                canvas.toBlob((blob) => {
                    if(blob && ws.readyState === WebSocket.OPEN) {
                        ws.send(blob);
                    }
                    // On demande la frame suivante immédiatement
                    requestAnimationFrame(capture);
                }, 'image/jpeg', 0.3); 
            }

            // Tentative de démarrage automatique au chargement
            window.addEventListener('load', () => {
                setTimeout(toggleLive, 500); 
            });
        </script>
    </body>
    </html>
    """
    return html_content


if __name__ == "__main__":
    import uvicorn
    import sys

    # Vérification des dépendances critiques
    missing = []
    for pkg in ["websockets", "cv2", "mediapipe", "ultralytics"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\n ERREUR : Packages manquants : {', '.join(missing)}")
        print(f"   Installez avec : pip install -r requirements.txt\n")
        sys.exit(1)

    # PORT : Railway/Render injectent leur propre PORT, en local on utilise 8000
    PORT = int(os.getenv("PORT", 8000))

    # SSL : uniquement en local si key.pem et cert.pem existent
    USE_SSL = not IS_CLOUD and os.path.exists("key.pem") and os.path.exists("cert.pem")

    base_url = CLOUD_URL or (f"https://{LOCAL_IP}:{PORT}" if USE_SSL else f"http://{LOCAL_IP}:{PORT}")

    print(f"\n" + "="*60)
    if IS_CLOUD:
        print(f" DALL JAMM EN LIGNE - MODE CLOUD")
    else:
        print(f" DALL JAMM EN LIGNE - MODE LOCAL {'(SSL)' if USE_SSL else ''}")
    print(f"="*60)
    print(f" URL principale : {base_url}")
    print(f" Admin          : {base_url}/admin")
    print(f" Client         : {base_url}/client")
    print(f" Manager        : {base_url}/manager")

    if not IS_CLOUD and qrcode:
        print(f"\n SCANNEZ CE CODE POUR CONNECTER VOTRE MOBILE :")
        qr = qrcode.QRCode(version=1, border=2)
        qr.add_data(f"{base_url}/mobile")
        qr.print_ascii(invert=True)

    if USE_SSL:
        print(f"\n  NAVIGATEUR : cliquez 'Parametres avances' puis 'Continuer' si Chrome bloque.")
    print(f"="*60 + "\n")

    ssl_kwargs = {"ssl_keyfile": "key.pem", "ssl_certfile": "cert.pem"} if USE_SSL else {}
    uvicorn.run(app, host="0.0.0.0", port=PORT, **ssl_kwargs)
class RfidAuth(BaseModel):
    uid: str

# Dernier événement RFID (pour affichage temps réel dans le dashboard)
LAST_RFID_EVENT = {"uid": None, "user": None, "balance": 0, "photo_url": "", "timestamp": 0}

@app.get("/api/last_rfid_event")
async def get_last_rfid_event():
    """Polling endpoint : le dashboard récupère le dernier scan RFID."""
    return LAST_RFID_EVENT

@app.post("/api/rfid_login")
async def rfid_login(req: RfidAuth):
    global LAST_RFID_EVENT
    uid = req.uid.strip().upper()

    # Réponse instantanée depuis le cache local
    user_name = RFID_USER_CACHE.get(uid, f"Badge_{uid[-4:] if len(uid) >= 4 else uid}")

    # Assigner immédiatement à toutes les caméras actives
    for cam_id in list(LATEST_FRAME_BYTES.keys()):
        CAMERA_USER_ASSIGNMENTS[cam_id] = user_name

    # Mise à jour immédiate de l'événement RFID (dashboard polling)
    LAST_RFID_EVENT = {
        "uid": uid,
        "user": user_name,
        "balance": 0,
        "photo_url": f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={uid}",
        "timestamp": time.time()
    }

    # Synchronisation Google en arrière-plan pour récupérer le vrai profil
    def sync_and_update():
        global LAST_RFID_EVENT
        try:
            resp = requests.post(APPS_SCRIPT_URL, json={
                "action": "login",
                "payload": {"rfidUid": uid}
            }, timeout=8)
            data = resp.json()
            if data.get("success") and data.get("user_data"):
                ud = data["user_data"]
                real_name = ud.get("name", user_name)
                RFID_USER_CACHE[uid] = real_name
                for cam_id in list(LATEST_FRAME_BYTES.keys()):
                    CAMERA_USER_ASSIGNMENTS[cam_id] = real_name
                LAST_RFID_EVENT = {
                    "uid": uid,
                    "user": real_name,
                    "balance": ud.get("balance", 0),
                    "photo_url": ud.get("photo_url", f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={uid}"),
                    "timestamp": time.time()
                }
        except Exception:
            pass
    threading.Thread(target=sync_and_update, daemon=True).start()

    return {"status": "success", "authorized": True, "user": user_name}

@app.get("/api/rfid_cache")
async def get_rfid_cache():
    """Retourne le cache local des badges RFID connus (pour diagnostic)."""
    return RFID_USER_CACHE

@app.get("/api/users_list")
async def get_users_list():
    """Récupère la liste des utilisateurs pour le manager (non-bloquant)."""
    loop = asyncio.get_event_loop()
    try:
        resp = await loop.run_in_executor(
            None,
            lambda: requests.post(APPS_SCRIPT_URL, json={"action": "getUsers"}, timeout=8)
        )
        return resp.json()
    except Exception:
        return [{"name": k, "phone": "---"} for k in WALLETS.keys()]

@app.post("/api/assign_badge")
async def assign_badge(phone: str = Form(...), rfid_uid: str = Form(...)):
    """Assigne un UID RFID à un utilisateur via son téléphone."""
    uid = rfid_uid.strip().upper()
    payload = {"action": "assignRfid", "payload": {"phone": phone, "rfidUid": uid}}
    loop = asyncio.get_event_loop()
    try:
        resp = await loop.run_in_executor(
            None,
            lambda: requests.post(APPS_SCRIPT_URL, json=payload, timeout=8)
        )
        return {"status": "success"} if resp.status_code == 200 else {"status": "error"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}