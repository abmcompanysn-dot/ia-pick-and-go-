"""
rfid_windows.py — Lecteur RFID USB Windows (mode clavier HID)
=============================================================
Les lecteurs RFID USB bon marché émulent un clavier :
ils tapent le numéro de la carte puis appuient sur Entrée.

Ce script :
  1. Écoute en arrière-plan les frappes du lecteur RFID
  2. Dès qu'une carte est scannée → envoie l'UID au serveur JEL DEM
  3. Le serveur identifie l'utilisateur, ouvre la session pick & go

UTILISATION :
  pip install pynput requests
  python rfid_windows.py

CONFIG : Modifier SERVER_URL ci-dessous si le serveur est sur un autre PC.
"""

import threading
import time
import requests
from pynput import keyboard

# ──────────────────────────────────────────────
# CONFIGURATION — à modifier selon votre setup
# ──────────────────────────────────────────────
SERVER_URL = "https://127.0.0.1:8000/api/rfid_login"  # URL du serveur JEL DEM
SSL_VERIFY = False          # False = accepte le certificat auto-signé
SCAN_TIMEOUT = 0.15         # secondes entre 2 touches → fin de scan si dépassé
MIN_UID_LEN = 4             # longueur minimale d'un UID valide
# ──────────────────────────────────────────────

_buffer = []
_last_key_time = 0.0
_lock = threading.Lock()


def send_uid(uid: str):
    uid = uid.strip().upper()
    if len(uid) < MIN_UID_LEN:
        return

    print(f"\n  Carte détectée : [{uid}]")
    try:
        resp = requests.post(
            SERVER_URL,
            json={"uid": uid},
            verify=SSL_VERIFY,
            timeout=5
        )
        data = resp.json()
        if data.get("authorized"):
            print(f"  Bienvenue, {data.get('user', uid)} !")
        else:
            print(f"  Accès refusé pour UID {uid}")
    except requests.exceptions.ConnectionError:
        print(f"  Serveur injoignable — vérifiez que main.py est lancé.")
    except Exception as e:
        print(f"  Erreur envoi RFID : {e}")


def flush_buffer():
    """Appelé après SCAN_TIMEOUT ms sans nouvelle touche → traite le buffer."""
    global _buffer
    with _lock:
        uid = "".join(_buffer).strip()
        _buffer = []
    if uid:
        send_uid(uid)


def on_press(key):
    global _buffer, _last_key_time

    now = time.time()
    elapsed = now - _last_key_time
    _last_key_time = now

    # Si trop de temps entre deux touches → nouveau scan
    if elapsed > SCAN_TIMEOUT and _buffer:
        with _lock:
            _buffer = []

    try:
        char = key.char
        if char and char.isprintable():
            with _lock:
                _buffer.append(char)
    except AttributeError:
        # Touche spéciale
        if key == keyboard.Key.enter:
            # Entrée = fin de scan RFID
            t = threading.Thread(target=flush_buffer, daemon=True)
            t.start()
        elif key == keyboard.Key.esc:
            print("\n  Arrêt du lecteur RFID Windows.")
            return False  # Stoppe le listener pynput


def main():
    print("=" * 50)
    print("  JEL DEM — Lecteur RFID Windows actif")
    print(f"  Serveur : {SERVER_URL}")
    print("  Passez une carte RFID devant le lecteur USB...")
    print("  [Echap] pour quitter")
    print("=" * 50)

    # Désactiver les avertissements SSL pour les certs auto-signés
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


if __name__ == "__main__":
    main()
