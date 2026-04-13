from ultralytics import YOLO
import torch
import os

def start_training():
    """
    Script pour entraîner votre propre modèle IA sur vos produits (Coca, Biscuit, etc.)
    Pré-requis : Avoir un dossier 'dataset' contenant vos images labellisées et un fichier data.yaml
    """
    print("Demarrage de l'entrainement YOLOv8...")
    
    # 1. Vérifier si le dataset existe
    yaml_path = os.path.abspath("dataset/data.yaml")
    
    if not os.path.exists(yaml_path):
        print("\nERREUR : Fichier 'dataset/data.yaml' introuvable.")
        print("Etape 1 : Allez sur https://universe.roboflow.com")
        print("Etape 2 : Recherchez 'Coca Cola' ou 'Retail Products'.")
        print("Etape 3 : Exportez le dataset au format 'YOLOv8' et dezippez-le dans un dossier 'dataset' ici.")
        return

    # 2. Charger le modèle de base (Nano = rapide et léger)
    # Cela va télécharger yolov8n.pt automatiquement si besoin
    print("Chargement du modele de base (YOLOv8n)...")
    model = YOLO("yolov8n.pt")

    # 3. Lancer l'entraînement
    # Détection automatique de CUDA (GPU NVIDIA)
    device = 0 if torch.cuda.is_available() else "cpu"
    
    print(f"Entrainement en cours sur : {yaml_path}")
    print(f"Appareil utilise : {'GPU NVIDIA' if device == 0 else 'CPU (Plus lent)'}")
    print("Prevoyez un peu de temps...")

    results = model.train(
        data=yaml_path, 
        epochs=100, 
        imgsz=640, 
        device=device,
        project="hyflex_training", # Dossier de sortie
        name="mon_modele_custom"
    )

    print("\n" + "="*60)
    print("ENTRAINEMENT TERMINE AVEC SUCCES !")
    print("Le cerveau de votre IA se trouve ici : hyflex_training/mon_modele_custom/weights/best.pt")
    print("Copiez 'best.pt' a cote de main.py et relancez le serveur pour tester !")
    print("="*60)

if __name__ == "__main__":
    start_training()
