"""
demo_local.py — Démonstration locale Pick & Go JEL DEM
=======================================================
Lance ce script sur ton PC pour voir en direct :
  - Detection personne + nom + solde
  - Detection produits + prix
  - Distance personne → produit
  - Signal quand un produit est pris

Usage :
    python demo_local.py
"""

import cv2
import numpy as np
import requests
import math
import time
import os
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ──────────────────────────────────────────
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxxSOZyptRBlGr0svsXlWzjANkMK8RRz03gVizG56nS6KsIfyVW0ghuyxonCY7ebqYGjQ/exec"
CAMERA_INDEX    = 0        # 0 = webcam intégrée, 1 = USB externe
RFID_USER       = None     # Sera défini après scan RFID
# ────────────────────────────────────────────────────

# Chargement YOLO
print("Chargement YOLO...")
try:
    from ultralytics import YOLO
    MODEL = YOLO("best.pt") if os.path.exists("best.pt") else YOLO("yolov8n.pt")
    print(f"  YOLO pret : {MODEL.model_name if hasattr(MODEL,'model_name') else 'OK'}")
except Exception as e:
    print(f"  YOLO non disponible : {e}")
    MODEL = None

# Chargement produits depuis Google Sheets
print("Chargement produits depuis Google Sheets...")
DB_PRODUITS = {}
try:
    r = requests.post(APPS_SCRIPT_URL, json={"action": "getProducts"}, timeout=8)
    DB_PRODUITS = r.json()
    print(f"  {len(DB_PRODUITS)} produits charges : {list(DB_PRODUITS.keys())}")
except Exception as e:
    print(f"  Impossible de joindre Google Sheets : {e}")
    DB_PRODUITS = {"coca": 1500, "eau": 500, "biscuit": 800}  # fallback

# Chargement utilisateurs depuis Google Sheets
print("Chargement utilisateurs...")
USERS_BY_NAME = {}
try:
    r2 = requests.post(APPS_SCRIPT_URL, json={"action": "getUsers"}, timeout=8)
    users = r2.json()
    for u in users:
        USERS_BY_NAME[u.get("name","").lower()] = u
    print(f"  {len(USERS_BY_NAME)} utilisateurs charges")
except Exception as e:
    print(f"  Utilisateurs non charges : {e}")

# ── ÉTAT GLOBAL ──────────────────────────────────────
current_user   = {"name": "Inconnu", "balance": 0}
alert_msg      = ""
alert_until    = 0
taken_products = []

def draw_corner_rect(img, x1, y1, x2, y2, color, thickness=2, corner_len=20):
    """Rectangle avec coins renforcés style HUD."""
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
    # Coins
    for (cx, cy, dx, dy) in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
        cv2.line(img, (cx, cy), (cx + dx*corner_len, cy), color, thickness+2)
        cv2.line(img, (cx, cy), (cx, cy + dy*corner_len), color, thickness+2)

def draw_label(img, text, x, y, bg_color, text_color=(255,255,255), scale=0.55):
    """Etiquette avec fond coloré."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(text, font, scale, 1)
    cv2.rectangle(img, (x, y - th - 6), (x + tw + 8, y + 2), bg_color, -1)
    cv2.putText(img, text, (x + 4, y - 2), font, scale, text_color, 1, cv2.LINE_AA)

def distance_px(cx1, cy1, cx2, cy2):
    return int(math.sqrt((cx2-cx1)**2 + (cy2-cy1)**2))

def set_alert(msg, duration=3):
    global alert_msg, alert_until
    alert_msg   = msg
    alert_until = time.time() + duration

def process_frame(frame):
    global current_user, taken_products

    if MODEL is None:
        cv2.putText(frame, "YOLO non disponible", (20,50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)
        return frame

    h, w = frame.shape[:2]
    overlay = frame.copy()

    try:
        results = MODEL.track(frame, persist=True, verbose=False,
                              conf=0.45, iou=0.5, tracker="botsort.yaml")
        res = results[0]
    except Exception as e:
        return frame

    person_centers = []   # [(cx, cy, track_id)]
    product_centers = []  # [(cx, cy, name, price)]

    if res.boxes.id is not None:
        boxes = res.boxes.xyxy.cpu().numpy().astype(int)
        ids   = res.boxes.id.cpu().numpy().astype(int)
        cls   = res.boxes.cls.cpu().numpy().astype(int)
        confs = res.boxes.conf.cpu().numpy()

        for box, tid, cid, conf in zip(boxes, ids, cls, confs):
            x1, y1, x2, y2 = box
            cx, cy = (x1+x2)//2, (y1+y2)//2
            name_cls = res.names[cid]

            if name_cls == "person":
                # ── PERSONNE ──────────────────────────────────
                person_centers.append((cx, cy, tid))
                color = (0, 242, 255)  # Cyan
                draw_corner_rect(overlay, x1, y1, x2, y2, color, corner_len=25)

                # Nom + solde
                uname   = current_user.get("name", "Inconnu")
                balance = current_user.get("balance", 0)
                label   = f"{uname}  |  {balance:,} FCFA"
                draw_label(overlay, label, x1, y1, (0, 130, 180))

                # ID de tracking
                cv2.putText(overlay, f"ID:{tid}", (x2-40, y1-5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

            else:
                # ── PRODUIT ────────────────────────────────────
                price = DB_PRODUITS.get(name_cls.lower(), 0)
                if price == 0:
                    color = (100, 100, 100)
                else:
                    color = (0, 255, 65)   # Vert

                product_centers.append((cx, cy, name_cls, price))
                draw_corner_rect(overlay, x1, y1, x2, y2, color, corner_len=15)

                plabel = f"{name_cls.upper()} : {price} FCFA"
                draw_label(overlay, plabel, x1, y2+4, (0, 80, 20))

    # ── DISTANCES PERSONNE → PRODUIT ──────────────────
    for (px, py, tid) in person_centers:
        for (qx, qy, pname, pprice) in product_centers:
            dist = distance_px(px, py, qx, qy)
            near = dist < 180  # pixels — en dessous = "proche"

            line_color = (0, 242, 255) if near else (80, 80, 80)
            cv2.line(overlay, (px, py), (qx, qy), line_color, 1 if not near else 2)

            mx, my = (px+qx)//2, (py+qy)//2
            cv2.putText(overlay, f"{dist}px", (mx, my),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (255,255,255) if near else (100,100,100), 1)

            if near and pprice > 0:
                cv2.putText(overlay, "PROCHE!", (qx-30, qy-30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,255,255), 2)

    # Blend overlay semi-transparent
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)

    # ── HUD BANDEAU HAUT ──────────────────────────────
    cv2.rectangle(frame, (0,0), (w, 38), (0,0,0), -1)
    ts = time.strftime("%d/%m/%Y %H:%M:%S")
    cv2.putText(frame, f"REC  {ts}", (10,24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,0,255), 1)
    cv2.putText(frame, "JEL DEM - PICK & GO", (w//2-100, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,242,255), 1)

    # ── HUD BANDEAU BAS ───────────────────────────────
    cv2.rectangle(frame, (0, h-45), (w, h), (0,0,0), -1)
    uinfo = f"Utilisateur: {current_user['name']}   Solde: {current_user['balance']:,} FCFA"
    cv2.putText(frame, uinfo, (10, h-15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    cv2.putText(frame, f"Produits: {len(DB_PRODUITS)} | [R]=RFID  [Q]=Quitter",
                (10, h-28), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (120,120,120), 1)

    # ── ALERTE ────────────────────────────────────────
    if time.time() < alert_until:
        av = 0.6 + 0.4*math.sin(time.time()*8)  # clignotement
        ac = (0, int(255*av), int(255*av))
        cv2.putText(frame, alert_msg, (w//2-200, h//2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, ac, 3, cv2.LINE_AA)

    return frame


def ask_rfid_manual():
    """Fenêtre simple pour saisir l'UID RFID ou le nom."""
    global current_user
    uid = input("\n  Entrez l'UID RFID ou le nom du client : ").strip()
    if not uid:
        return
    # Chercher dans Google Sheets
    try:
        r = requests.post(APPS_SCRIPT_URL, json={
            "action": "login",
            "payload": {"rfidUid": uid}
        }, timeout=8)
        data = r.json()
        if data.get("success") and data.get("user_data"):
            ud = data["user_data"]
            current_user = {"name": ud.get("name","?"), "balance": ud.get("balance",0)}
            set_alert(f"Bienvenue {current_user['name']} !", 4)
            print(f"  → {current_user['name']} | {current_user['balance']} FCFA")
        else:
            current_user = {"name": uid, "balance": 0}
            set_alert(f"Badge inconnu : {uid}", 3)
    except Exception as e:
        print(f"  Erreur Google Sheets : {e}")
        current_user = {"name": uid, "balance": 0}


def main():
    print("\n" + "="*55)
    print("  JEL DEM — DEMO LOCALE PICK & GO")
    print("  [R] = Identifier utilisateur (RFID / Nom)")
    print("  [Q] = Quitter")
    print("="*55 + "\n")

    # Essai avec DirectShow (plus compatible Windows)
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened() or not cap.read()[0]:
        print("DirectShow échoué, essai caméra 1...")
        cap.release()
        cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"ERREUR : Aucune caméra trouvée. Branchez une webcam USB.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    cv2.namedWindow("JEL DEM - Pick & Go", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("JEL DEM - Pick & Go", 1280, 720)

    print("Caméra ouverte. Appuyez sur [R] pour identifier un utilisateur.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = process_frame(frame)
        cv2.imshow("JEL DEM - Pick & Go", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            # Identifier l'utilisateur (input dans le terminal)
            import threading
            t = threading.Thread(target=ask_rfid_manual, daemon=True)
            t.start()

    cap.release()
    cv2.destroyAllWindows()
    print("Demo terminée.")


if __name__ == "__main__":
    main()
