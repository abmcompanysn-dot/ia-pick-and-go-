from ultralytics import YOLO
import os

def start_training():
    """
    Script pour entraîner votre propre modèle IA sur vos produits (Coca, Biscuit, etc.)
    Pré-requis : Avoir un dossier 'dataset' contenant vos images labellisées et un fichier data.yaml
    """
    print("🚀 Démarrage de l'entraînement YOLOv8...")
    
    # 1. Vérifier si le dataset existe
    # Le fichier data.yaml est créé par Roboflow lors de l'export
    yaml_path = os.path.abspath("dataset/data.yaml")
    
    if not os.path.exists("dataset/data.yaml"):
        print("\n❌ ERREUR : Fichier 'dataset/data.yaml' introuvable.")
        print("👉 Étape 1 : Allez sur Roboflow.com, importez vos photos de 'produits_dataset'.")
        print("👉 Étape 2 : Annotez vos produits (dessinez les cadres).")
        print("👉 Étape 3 : Exportez le dataset au format 'YOLOv8' et dézippez-le dans un dossier 'dataset' ici.")
        return

    # 2. Charger le modèle de base (Nano = rapide et léger)
    # Cela va télécharger yolov8n.pt automatiquement si besoin
    print("🔄 Chargement du modèle de base...")
    model = YOLO("yolov8n.pt")

    # 3. Lancer l'entraînement
    # epochs = 100 : L'IA va revoir les images 100 fois
    # imgsz = 640 : Taille standard des images
    print(f"🔥 Entraînement en cours sur : {yaml_path}")
    print("☕ Cela peut prendre du temps (30min à plusieurs heures selon votre PC)...")
    
    results = model.train(
        data=yaml_path, 
        epochs=100, 
        imgsz=640,
        project="hyflex_training", # Dossier de sortie
        name="mon_modele_custom"
    )

    print("\n" + "="*60)
    print("✅ ENTRAÎNEMENT TERMINÉ AVEC SUCCÈS !")
    print("👉 Le cerveau de votre IA se trouve ici : hyflex_training/mon_modele_custom/weights/best.pt")
    print("👉 Copiez 'best.pt' à côté de main.py et relancez le serveur pour tester !")
    print("="*60)

if __name__ == "__main__":
    start_training()
