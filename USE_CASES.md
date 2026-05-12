# Cas d'Utilisation - Système JEL DEM (Hyflex Shop & Go)

## 1. Mode "Pick & Go" (IA Intelligente)
*   **Identification** : L'utilisateur entre dans le magasin. Il est reconnu par **Face ID** ou scanne son **QR Code** à l'entrée.
*   **Shopping** : L'utilisateur prend des articles sur les étagères. Les caméras (YOLOv8 + MediaPipe) suivent ses mouvements.
*   **Paiement** : L'utilisateur sort simplement du magasin. Le système détecte la disparition de l'objet et le débit automatique du wallet est effectué.
*   **Notification** : Un reçu est envoyé instantanément par email via Google Apps Script.

## 2. Mode "No-Camera" (Scan & Pay Manuel)
*   **Identification** : L'utilisateur utilise son application mobile pour s'identifier.
*   **Shopping** : L'utilisateur utilise la caméra de son **smartphone** pour scanner le code-barres ou le nom du produit via l'interface mobile.
*   **Paiement** : L'utilisateur clique sur "Payer" sur son téléphone. Le serveur FastAPI valide le prix et communique avec Google Sheets pour débiter le solde.
*   **Usage** : Idéal pour les zones sans couverture caméra ou pour les clients préférant le contrôle manuel.

## 3. Mode "RFID Access Control" (ESP32)
*   **Identification** : L'utilisateur passe son badge **RFID** (MFRC522) devant le terminal à l'entrée.
*   **Action** : L'ESP32 envoie l'UID à l'Apps Script. Si le solde est suffisant (> 0), le relais active la gâche électrique de la porte.
*   **Logging** : L'entrée est loguée dans la feuille "Transactions" comme un accès autorisé.

## 4. Inscription Hyflex (Onboarding)
*   **Formulaire** : Le nouveau client choisit son profil (**Étudiant** ou **Professionnel**).
*   **Biométrie** : Il effectue un scan facial (5 poses) pour configurer son Face ID.
*   **Confirmation** : Un email de bienvenue est envoyé avec les instructions et son type de compte.
*   **RFID** : Un administrateur peut lier un badge physique au compte via le dashboard manager.