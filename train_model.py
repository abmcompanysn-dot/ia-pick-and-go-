from ultralytics import YOLO
import torch
import os
import shutil
import random

def prepare_yolo_dataset(source_folder="produits_dataset", target_folder="dataset"):
    """
    Prepare automatiquement le dossier dataset pour YOLOv8 a partir des photos du Mode Training.
    Cree les dossiers, repartit les images et genere le fichier data.yaml correct.
    """
    print(f"Preparation du dataset a partir de {source_folder}...")
    
    if not os.path.exists(source_folder) or not os.listdir(source_folder):
        return False, "Le dossier produits_dataset est vide. Utilisez le Mode Training sur mobile d'abord."

    # 1. Identifier les classes (produits)
    images = [f for f in os.listdir(source_folder) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    if not images:
        return False, "Aucune image trouvee dans produits_dataset."

    # On extrait le nom du produit (avant le _) pour creer les classes
    classes = sorted(list(set([f.split('_')[0] for f in images])))
    class_to_id = {name: i for i, name in enumerate(classes)}

    # 2. Nettoyer et creer la structure YOLO
    if os.path.exists(target_folder):
        try:
            shutil.rmtree(target_folder)
        except Exception:
            # Si le dossier est verrouille, on essaie au moins de vider les sous-dossiers
            pass

    for sub in ['train', 'val']:
        os.makedirs(os.path.join(target_folder, sub, 'images'), exist_ok=True)
        os.makedirs(os.path.join(target_folder, sub, 'labels'), exist_ok=True)

    # 3. Repartir les images (80% entrainement, 20% validation)
    random.shuffle(images)
    split_idx = int(len(images) * 0.8)
    
    for i, filename in enumerate(images):
        subset = 'train' if i < split_idx else 'val'
        class_name = filename.split('_')[0]
        class_id = class_to_id[class_name]

        # Copier l'image vers le dossier d'entrainement
        src_img = os.path.join(source_folder, filename)
        dst_img = os.path.join(target_folder, subset, 'images', filename)
        shutil.copy(src_img, dst_img)

        # Generer un label automatique (on considere que le produit occupe toute la photo)
        label_name = os.path.splitext(filename)[0] + ".txt"
        with open(os.path.join(target_folder, subset, 'labels', label_name), "w") as f:
            # Format YOLO: <id_classe> <x_centre> <y_centre> <largeur> <hauteur>
            f.write(f"{class_id} 0.5 0.5 1.0 1.0\n")

    # 4. Generer le fichier data.yaml correct
    yaml_path = os.path.join(target_folder, "data.yaml")
    yaml_content = f"""
train: {os.path.abspath(os.path.join(target_folder, 'train', 'images'))}
val: {os.path.abspath(os.path.join(target_folder, 'val', 'images'))}

nc: {len(classes)}
names: {classes}
"""
    with open(yaml_path, "w") as f:
        f.write(yaml_content.strip())

    print(f"Succes : {len(classes)} produits detectes ({', '.join(classes)}).")
    return True, os.path.abspath(yaml_path)

def start_training():
    """
    Script pour entraîner votre propre modèle IA sur vos produits (Coca, Biscuit, etc.)
    """
    print("Demarrage de l'entrainement YOLOv8...")
    
    # 1. Preparation automatique du dataset a partir de vos photos
    success, result = prepare_yolo_dataset()
    
    if not success:
        print(f"\nERREUR : {result}")
        return
    
    yaml_path = result

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
