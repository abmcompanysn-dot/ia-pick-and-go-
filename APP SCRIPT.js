// c:\Users\Admin\OneDrive\Pictures\im\Desktop\no mini projet\ia abm edupilote\APP SCRIPT.js

// --- MENU PERSONNALISÉ ---
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('🛡️ HYFLEX ADMIN')
    .addItem('⚙️ Initialiser les Feuilles', 'setupDatabase')
    .addItem('🔄 Synchroniser la Config PayDunya', 'syncConfigFromSheet')
    .addToUi();
}

// --- GESTION DYNAMIQUE DES PARAMÈTRES ---
function getPayDunyaConfig() {
  const props = PropertiesService.getScriptProperties();
  return {
    masterKey: props.getProperty('PAYDUNYA_MASTER_KEY') || "",
    privateKey: props.getProperty('PAYDUNYA_PRIVATE_KEY') || "",
    token: props.getProperty('PAYDUNYA_TOKEN') || "",
    mode: props.getProperty('PAYDUNYA_MODE') || "test" // "test" ou "live"
  };
}

function syncConfigFromSheet() {
  const ss = getDb();
  const sheet = ss.getSheetByName('Configuration');
  if (!sheet) {
    SpreadsheetApp.getUi().alert('❌ Erreur : Onglet "Configuration" introuvable. Lancez d\'abord l\'initialisation.');
    return;
  }
  
  const data = sheet.getDataRange().getValues();
  const props = PropertiesService.getScriptProperties();
  
  // On saute l'en-tête (ligne 0)
  for (let i = 1; i < data.length; i++) {
    if (data[i][0]) props.setProperty(data[i][0], data[i][1].toString());
  }
  SpreadsheetApp.getUi().alert('✅ Configuration PayDunya synchronisée avec succès !');
}

// Force la détection des autorisations Drive : DriveApp.getFoldersByName

// ON UTILISE LA FEUILLE ACTIVE DIRECTEMENT (Plus besoin d'ID)
function getDb() {
  return SpreadsheetApp.getActiveSpreadsheet();
}

// --- FONCTION D'INITIALISATION AUTOMATIQUE ---
// Cette fonction crée les onglets s'ils n'existent pas
function setupDatabase() {
  const ss = getDb();
  const sheets = ['Utilisateurs', 'Produits', 'Transactions', 'Configuration'];
  
  // En-têtes pour chaque feuille
  const headers = {
    'Utilisateurs': ['ID_Utilisateur', 'Nom', 'Email', 'Telephone', 'Solde_FCFA', 'Date_Inscription', 'Mot_de_Passe', 'RFID_ID', 'Face_ID_Active'],
    'Produits': ['ID_Produit', 'Nom_Produit', 'Prix_FCFA', 'Stock_Actuel', 'Rayon'],
    'Transactions': ['ID_Transaction', 'Date_Heure', 'ID_Utilisateur', 'Nom_Client', 'ID_Produit', 'Nom_Produit', 'Montant_FCFA', 'Camera_ID'],
    'Configuration': ['Clé de Paramètre', 'Valeur']
  };

  sheets.forEach(name => {
    let sheet = ss.getSheetByName(name);
    if (!sheet) {
      sheet = ss.insertSheet(name);
      sheet.appendRow(headers[name]); // Ajoute les en-têtes
      
      if (name === 'Configuration') {
        sheet.appendRow(['PAYDUNYA_MASTER_KEY', '']);
        sheet.appendRow(['PAYDUNYA_PRIVATE_KEY', '']);
        sheet.appendRow(['PAYDUNYA_TOKEN', '']);
        sheet.appendRow(['PAYDUNYA_MODE', 'test']);
      }
    }
  });
}

// --- API WEB ---
function doPost(e) {
  const props = PropertiesService.getScriptProperties();
  
  try {
    const ss = getDb();
    let data = JSON.parse(e.postData.contents);
    let action = data.action;

    // Détection automatique d'une notification IPN PayDunya 
    // (Pas de champ 'action' mais présence de 'token' et 'status')
    if (!action && data.token && data.status) {
      action = 'paydunya_ipn';
    }

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
       const phone = data.payload.phone || "";
       const password = data.payload.password || "1234";
       const rfid = data.payload.rfid || "";
       
       sheet.appendRow([newId, data.payload.name, email, phone, solde, new Date(), password, rfid, "NON"]);
       
       // ENVOI D'EMAIL DE BIENVENUE
       if (email !== "Non renseigné") {
         const subject = "Bienvenue chez JEL DEM !";
         const body = `Bonjour ${data.payload.name},\n\n` +
                      `Votre compte JEL DEM a été créé avec succès.\n` +
                      `Vous pouvez maintenant utiliser votre QR Code ou votre carte RFID pour vos achats.\n\n` +
                      `Cordialement,\nL'équipe JEL DEM`;
         MailApp.sendEmail(email, subject, body);
       }
       
       result = { success: true, userId: newId };

    } else if (action === 'assignRfid') {
       let sheet = ss.getSheetByName("Utilisateurs");
       const rows = sheet.getDataRange().getValues();
       const phone = data.payload.phone;
       const rfidUid = data.payload.rfidUid;
       
       for (let i = 1; i < rows.length; i++) {
         if (rows[i][3].toString() === phone.toString()) {
           sheet.getRange(i + 1, 8).setValue(rfidUid);
           result = { success: true };
           break;
         }
       }

    } else if (action === 'updatePassword') {
       let sheet = ss.getSheetByName("Utilisateurs");
       const rows = sheet.getDataRange().getValues();
       const phone = data.payload.phone;
       const newPass = data.payload.newPassword;
       
       for (let i = 1; i < rows.length; i++) {
         if (rows[i][3].toString() === phone.toString()) {
           sheet.getRange(i + 1, 7).setValue(newPass);
           result = { success: true };
           break;
         }
       }

    } else if (action === 'rechargeBalance') {
       let sheet = ss.getSheetByName("Utilisateurs");
       const rows = sheet.getDataRange().getValues();
       const phone = data.payload.phone;
       const amount = parseInt(data.payload.amount);
       
       for (let i = 1; i < rows.length; i++) {
         if (rows[i][3].toString() === phone.toString()) {
           const currentBalance = parseInt(rows[i][4]);
           const newBalance = currentBalance + amount;
           sheet.getRange(i + 1, 5).setValue(newBalance);
           result = { success: true, newBalance: newBalance };
           break;
         }
       }
       if (!result.success) result = { success: false, message: "Utilisateur non trouvé" };

    } else if (action === 'login') {
       let sheet = ss.getSheetByName("Utilisateurs");
       const rows = sheet.getDataRange().getValues();
       const identifier = data.payload.phone || data.payload.rfidUid || data.payload.faceId;
       const password = data.payload.password;
       
       for (let i = 1; i < rows.length; i++) {
         const matchPhone = data.payload.phone && rows[i][3].toString() === identifier.toString();
         const matchRfid = data.payload.rfidUid && rows[i][7].toString() === identifier.toString();
         const matchFace = data.payload.faceId && rows[i][1].toString() === identifier.toString(); // Match par nom/ID visage
         
         if ((matchPhone || matchRfid || matchFace) && (password ? rows[i][6].toString() === password.toString() : true)) {
           // Récupérer les transactions pour l'utilisateur
           let transSheet = ss.getSheetByName("Transactions");
           let transactions = [];
           if (transSheet) {
             const tRows = transSheet.getDataRange().getValues();
             for (let j = 1; j < tRows.length; j++) {
               if (tRows[j][2].toString() === rows[i][0].toString() || tRows[j][2].toString() === phone.toString()) {
                 transactions.push({ produit: tRows[j][5], montant: tRows[j][6], timestamp: tRows[j][1] });
               }
             }
           }
           // On renvoie authorized: true pour l'ESP32
           result = { 
             success: true, 
             authorized: true, 
             user_data: { 
               name: rows[i][1], 
               balance: rows[i][4], 
               phone: rows[i][3], 
               face_id: rows[i][8], 
               email: rows[i][2],
               balance: rows[i][4],
               transactions: transactions
             } 
           };
           break;
         }
       }
       if (!result.success) result = { success: false, authorized: false, message: "Accès refusé" };

    } else if (action === 'logTransaction') {
       let sheet = ss.getSheetByName("Transactions");
       if (!sheet) { setupDatabase(); sheet = ss.getSheetByName("Transactions"); }
       
       const newId = "TRANS_" + new Date().getTime();
       sheet.appendRow([
         newId, new Date(), data.payload.userId, data.payload.userName, 
         data.payload.productId, data.payload.productName, data.payload.price, data.payload.cameraId
       ]);
       
       // ENVOI D'EMAIL AUTOMATIQUE
       if (data.payload.userEmail && data.payload.userEmail !== "Non renseigné") {
         const subject = "Confirmation d'achat - DALL JAMM";
         const body = `Bonjour ${data.payload.userName},\n\n` +
                      `Votre achat de ${data.payload.productName} (${data.payload.price} FCFA) a été validé.\n` +
                      `Merci de votre confiance !\n\n` +
                      `L'équipe DALL JAMM`;
         MailApp.sendEmail(data.payload.userEmail, subject, body);
       }
       
       result = { transactionId: newId };

    } else if (action === 'saveSettings') {
       // Sauvegarde des clés de l'API
       props.setProperty('PAYDUNYA_MASTER_KEY', data.payload.masterKey);
       props.setProperty('PAYDUNYA_PRIVATE_KEY', data.payload.privateKey);
       props.setProperty('PAYDUNYA_TOKEN', data.payload.token);
       props.setProperty('PAYDUNYA_MODE', data.payload.mode);
       result = { success: true };

    } else if (action === 'getSettings') {
       // Récupère les paramètres actuels
       result = { 
         success: true, 
         settings: getPayDunyaConfig()
       };

    } else if (action === 'getUserProfile') {
       // Utilisé par le scan QR Code pour afficher les infos
       let sheet = ss.getSheetByName("Utilisateurs");
       const rows = sheet.getDataRange().getValues();
       const phone = data.payload.phone;
       for (let i = 1; i < rows.length; i++) {
         if (rows[i][3].toString() === phone.toString()) {
            // On cherche l'image dans Drive
            let faceUrl = "";
            const folderName = "HYFLEX_DATASET";
            const folders = DriveApp.getFoldersByName(folderName);
            if (folders.hasNext()) {
              const folder = folders.next();
              const files = folder.getFilesByName(`FACE_${phone}.jpg`);
              if (files.hasNext()) {
                faceUrl = files.next().getDownloadUrl();
              }
            }
            
            result = { 
              success: true, 
              user: { 
                name: rows[i][1], 
                balance: rows[i][4], 
                phone: rows[i][3],
                face_active: rows[i][8],
                face_url: faceUrl
              } 
            };
            break;
         }
       }

    } else if (action === 'initiatePayDunya') {
       // Intégration réelle API PayDunya (Exemple simplifié)
       const payload = {
         invoice: { total_amount: data.payload.amount, description: "Recharge JEL DEM" },
         store: { name: "JEL DEM SHOP" },
         custom_data: { phone: data.payload.phone }
       };
       
       // Simulation de validation immédiate pour Wave (en attendant la configuration IPN)
       return doPost({postData: {contents: JSON.stringify({
         token: "SIMULATED_WAVE_TOKEN",
         status: "completed",
         invoice: { total_amount: data.payload.amount },
         custom_data: { phone: data.payload.phone }
       })}});

    } else if (action === 'paydunya_ipn') {
       // LOGIQUE IPN RÉELLE : PayDunya envoie le token de la transaction
       const token = data.token || data.invoice_token;
       if (!token) return ContentService.createTextOutput("Token manquant").setMimeType(ContentService.MimeType.TEXT);
       
       // 1. Vérification de sécurité CRUCIALE auprès de l'API PayDunya
       const verification = verifyPayDunyaTransaction(token);
       
       // On vérifie que le statut est "completed" (ou "success")
       if (verification && (verification.status === 'completed' || verification.response_code === "00")) {
         const amount = parseInt(verification.invoice ? verification.invoice.total_amount : verification.total_amount);
         
         // On récupère le téléphone stocké dans custom_data lors de l'init
         const customData = verification.custom_data || verification.metadata;
         const phone = customData ? customData.phone : null;
         
         if (!phone) return ContentService.createTextOutput("Données utilisateur manquantes").setMimeType(ContentService.MimeType.TEXT);

         let sheet = ss.getSheetByName("Utilisateurs");
         const rows = sheet.getDataRange().getValues();
         
         for (let i = 1; i < rows.length; i++) {
           if (rows[i][3].toString() === phone.toString()) {
             const oldBalance = parseInt(rows[i][4]);
             const newBalance = oldBalance + amount;
             sheet.getRange(i + 1, 5).setValue(newBalance);
             
             // Enregistrement de la recharge dans l'historique
             let transSheet = ss.getSheetByName("Transactions");
             transSheet.appendRow(["RECH_" + token, new Date(), rows[i][0], rows[i][1], "WALLET", "Recharge PayDunya", amount, "SYSTEM"]);
             
             result = { success: true, message: "Balance mise à jour via IPN" };
             
             // Optionnel : Envoyer un email de confirmation
             MailApp.sendEmail(rows[i][2], "Confirmation de dépôt", `Votre compte a été crédité de ${amount} FCFA.`);
             break;
           }
         }
       } else {
         result = { success: false, message: "Transaction non complétée ou invalide" };
       }

    }  else if (action === 'uploadImage') {
       // NOTE: Ce bloc nécessite l'autorisation "Google Drive API" (scope: https://www.googleapis.com/auth/drive) lors du déploiement.
       // SAUVEGARDE BIOMÉTRIQUE : Stockage des visages pour la reconnaissance
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
         
         // Mise à jour du statut Face ID dans la feuille Utilisateurs
         const userPhone = data.payload.phone;
         const userSheet = ss.getSheetByName("Utilisateurs");
         const uRows = userSheet.getDataRange().getValues();
         for (let k = 1; k < uRows.length; k++) {
           if (uRows[k][3].toString() === userPhone.toString()) {
             userSheet.getRange(k + 1, 9).setValue("OUI");
             break;
           }
         }

         result = { success: true, url: file.getUrl(), message: "Biométrie enregistrée" };
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

/**
 * Vérifie l'état d'une transaction directement auprès de l'API PayDunya
 */
function verifyPayDunyaTransaction(token) {
  const config = getPayDunyaConfig();
  const baseUrl = config.mode === "live" 
    ? "https://paydunya.com/api/v1/checkout-invoice/confirm/" 
    : "https://paydunya.com/sandbox-api/v1/checkout-invoice/confirm/";
    
  const url = baseUrl + token;
  const options = {
    "method": "get",
    "headers": {
      "PAYDUNYA-MASTER-KEY": config.masterKey,
      "PAYDUNYA-PRIVATE-KEY": config.privateKey,
      "PAYDUNYA-TOKEN": config.token,
      "Content-Type": "application/json"
    },
    "muteHttpExceptions": true
  };
  
  const response = UrlFetchApp.fetch(url, options);
  return JSON.parse(response.getContentText());
}
