// c:\Users\Admin\OneDrive\Pictures\im\Desktop\no mini projet\ia abm edupilote\APP SCRIPT.js

// ON UTILISE LA FEUILLE ACTIVE DIRECTEMENT (Plus besoin d'ID)
function getDb() {
  return SpreadsheetApp.getActiveSpreadsheet();
}

// --- FONCTION D'INITIALISATION AUTOMATIQUE ---
// Cette fonction crée les onglets s'ils n'existent pas
function setupDatabase() {
  const ss = getDb();
  const sheets = ['Utilisateurs', 'Produits', 'Transactions'];
  
  // En-têtes pour chaque feuille
  const headers = {
    'Utilisateurs': ['ID_Utilisateur', 'Nom', 'Email', 'Solde_FCFA', 'Date_Inscription'],
    'Produits': ['ID_Produit', 'Nom_Produit', 'Prix_FCFA', 'Stock_Actuel', 'Rayon'],
    'Transactions': ['ID_Transaction', 'Date_Heure', 'ID_Utilisateur', 'Nom_Client', 'ID_Produit', 'Nom_Produit', 'Montant_FCFA', 'Camera_ID']
  };

  sheets.forEach(name => {
    let sheet = ss.getSheetByName(name);
    if (!sheet) {
      sheet = ss.insertSheet(name);
      sheet.appendRow(headers[name]); // Ajoute les en-têtes
    }
  });
}

// --- API WEB ---
function doPost(e) {
  // On s'assure que la DB est prête à chaque requête (ou on pourrait le faire une seule fois)
  // Pour la performance, on suppose que setupDatabase a été lancé une fois, 
  // mais on gère les erreurs si les feuilles manquent.
  
  try {
    const ss = getDb();
    const data = JSON.parse(e.postData.contents);
    const action = data.action;
    let result = {};

    if (action === 'getProducts') {
      const sheet = ss.getSheetByName("Produits");
      if (!sheet) { setupDatabase(); return ContentService.createTextOutput(JSON.stringify({})).setMimeType(ContentService.MimeType.JSON); }
      
      const rows = sheet.getDataRange().getValues();
      let products = {};
      for (let i = 1; i < rows.length; i++) {
        if (rows[i][1] && rows[i][2]) {
          products[rows[i][1].toLowerCase()] = rows[i][2];
        }
      }
      result = products;

    } else if (action === 'addProduct') {
      let sheet = ss.getSheetByName("Produits");
      if (!sheet) { setupDatabase(); sheet = ss.getSheetByName("Produits"); }
      
      const newId = "PROD_" + new Date().getTime();
      sheet.appendRow([
        newId,
        data.payload.name,
        data.payload.price,
        data.payload.stock || 100,
        data.payload.shelf || "Rayon A"
      ]);
      result = { success: true, message: "Produit ajouté" };

    } else if (action === 'registerClient' || action === 'registerUser') {
       // Gère l'inscription depuis le Python (registerClient) ou ailleurs
       let sheet = ss.getSheetByName("Utilisateurs");
       if (!sheet) { setupDatabase(); sheet = ss.getSheetByName("Utilisateurs"); }
       
       const newId = "USER_" + new Date().getTime();
       const solde = data.payload.balance || 0;
       const email = data.payload.email || "Non renseigné";
       sheet.appendRow([newId, data.payload.name, email, solde, new Date()]);
       result = { userId: newId };

    } else if (action === 'logTransaction') {
       let sheet = ss.getSheetByName("Transactions");
       if (!sheet) { setupDatabase(); sheet = ss.getSheetByName("Transactions"); }
       
       const newId = "TRANS_" + new Date().getTime();
       sheet.appendRow([
         newId, new Date(), data.payload.userId, data.payload.userName, 
         data.payload.productId, data.payload.productName, data.payload.price, data.payload.cameraId
       ]);
       result = { transactionId: newId };

    } else if (action === 'uploadImage') {
       // NOUVEAU: Sauvegarde les images (Visages/Produits) dans Google Drive
       try {
         const folderName = "HYFLEX_DATASET";
         const folders = DriveApp.getFoldersByName(folderName);
         let folder;
         if (folders.hasNext()) {
           folder = folders.next();
         } else {
           folder = DriveApp.createFolder(folderName);
         }
         const blob = Utilities.newBlob(Utilities.base64Decode(data.payload.image), MimeType.JPEG, data.payload.filename);
         const file = folder.createFile(blob);
         result = { success: true, url: file.getUrl() };
       } catch (e) {
         result = { success: false, error: e.toString() };
       }
    }

    return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);

  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({ status: 'error', message: error.message })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  // Lancez l'URL du script dans le navigateur une fois pour initialiser
  setupDatabase();
  return HtmlService.createHtmlOutput("<h1>✅ Système HYFLEX Initialisé</h1><p>Les onglets ont été créés dans votre Google Sheet.</p>");
}
