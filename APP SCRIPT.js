// c:\Users\Admin\OneDrive\Pictures\im\Desktop\no mini projet\ia abm edupilote\APP SCRIPT.js

// --- MENU PERSONNALISÉ ---
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('HYFLEX ADMIN')
    .addItem('Initialiser les Feuilles', 'setupDatabase')
    .addItem('Synchroniser la Config PayDunya', 'syncConfigFromSheet')
    .addToUi();
}

// --- GESTION DYNAMIQUE DES PARAMÈTRES ---
function getPayDunyaConfig() {
  const ss = getDb();
  const sheet = ss.getSheetByName('Configuration');
  if (sheet) {
    const data = sheet.getDataRange().getValues();
    let config = {};
    data.forEach(row => {
      if (row[0] === 'PAYDUNYA_MASTER_KEY') config.masterKey = row[1];
      if (row[0] === 'PAYDUNYA_PRIVATE_KEY') config.privateKey = row[1];
      if (row[0] === 'PAYDUNYA_PUBLIC_KEY') config.publicKey = row[1];
      if (row[0] === 'PAYDUNYA_TOKEN') config.token = row[1];
      if (row[0] === 'PAYDUNYA_MODE') config.mode = row[1];
      if (row[0] === 'PYTHON_SERVER_URL') config.pythonUrl = row[1];
    });
    if (config.masterKey || config.pythonUrl) return config;
  }

  const props = PropertiesService.getScriptProperties();
  return {
    masterKey: props.getProperty('PAYDUNYA_MASTER_KEY') || "",
    privateKey: props.getProperty('PAYDUNYA_PRIVATE_KEY') || "",
    publicKey: props.getProperty('PAYDUNYA_PUBLIC_KEY') || "",
    token: props.getProperty('PAYDUNYA_TOKEN') || "",
    mode: props.getProperty('PAYDUNYA_MODE') || "test",
    pythonUrl: props.getProperty('PYTHON_SERVER_URL') || ""
  };
}

function syncConfigFromSheet() {
  const ss = getDb();
  const sheet = ss.getSheetByName('Configuration');
  if (!sheet) {
    SpreadsheetApp.getUi().alert('Erreur : Onglet "Configuration" introuvable. Lancez d\'abord l\'initialisation.');
    return;
  }
  
  const data = sheet.getDataRange().getValues();
  const props = PropertiesService.getScriptProperties();
  
  // On saute l'en-tête (ligne 0)
  for (let i = 1; i < data.length; i++) {
    if (data[i][0]) props.setProperty(data[i][0], data[i][1].toString());
  }
  SpreadsheetApp.getUi().alert('Configuration PayDunya synchronisee avec succes !');
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
        sheet.appendRow(['PAYDUNYA_PUBLIC_KEY', '']);
        sheet.appendRow(['PAYDUNYA_TOKEN', '']);
        sheet.appendRow(['PAYDUNYA_MODE', 'test']);
        sheet.appendRow(['PYTHON_SERVER_URL', '']);
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

    } else if (action === 'getUsers') {
      const sheet = ss.getSheetByName("Utilisateurs");
      if (!sheet) { setupDatabase(); return ContentService.createTextOutput(JSON.stringify([])).setMimeType(ContentService.MimeType.JSON); }
      
      const rows = sheet.getDataRange().getValues();
      let users = [];
      for (let i = 1; i < rows.length; i++) {
        if (rows[i][1]) {
          users.push({ name: rows[i][1], phone: rows[i][3], balance: rows[i][4], rfid: rows[i][7] });
        }
      }
      result = users;

    } else if (action === 'requestDoorAccess') {
      // RELAIS VERS LE SERVEUR PYTHON (FastAPI)
      const config = getPayDunyaConfig();
      const pythonServerUrl = config.pythonUrl + "/api/rfid_login"; 
      
      const forwardPayload = {
        uid: data.data.rfidId
      };

      const options = {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify(forwardPayload),
        muteHttpExceptions: true
      };

      try {
        const response = UrlFetchApp.fetch(pythonServerUrl, options);
        const serverResponse = JSON.parse(response.getContentText());
        
        // On reformate la réponse pour que l'ESP32 la comprenne bien
        result = {
          authorized: serverResponse.authorized || false,
          user_data: {
            name: serverResponse.user || "Utilisateur",
            balance: serverResponse.balance || 0
          }
        };
      } catch (e) {
        result = { authorized: false, message: "Erreur liaison Python: " + e.toString() };
      }

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
         sendStyledEmail(
           email, 
           "Bienvenue chez JEL DEM !", 
           "Félicitations, votre compte est prêt !", 
           `Bonjour <b>${data.payload.name}</b>,<br><br>` +
           `Votre compte JEL DEM a été créé avec succès. Vous faites maintenant partie de l'avenir du shopping connecté.<br><br>` +
           `Vous pouvez dès à présent utiliser votre <b>QR Code</b> ou votre <b>badge RFID</b> pour effectuer vos achats en toute liberté.`
         );
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
               if (tRows[j][2].toString() === rows[i][0].toString() || tRows[j][2].toString() === rows[i][3].toString()) {
                 transactions.push({ produit: tRows[j][5], montant: tRows[j][6], timestamp: tRows[j][1] });
               }
             }
           }
           // On renvoie les informations complètes pour l'ESP32 et l'Interface
           result = { 
             success: true, 
             authorized: true, 
             user_data: { 
               name: rows[i][1], 
               balance: parseFloat(rows[i][4]) || 0, 
               phone: rows[i][3].toString(), 
               face_id: rows[i][8], 
               email: rows[i][2],
               photo_url: "https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=" + rows[i][3],
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
         sendStyledEmail(
           data.payload.userEmail, 
           "Reçu de paiement - JEL DEM", 
           "Merci pour votre achat", 
           `Bonjour <b>${data.payload.userName}</b>,<br><br>` +
           `Nous vous confirmons l'achat suivant :<br>` +
           `🛒 Produit : <b>${data.payload.productName}</b><br>` +
           `💰 Montant : <b>${data.payload.price} FCFA</b>`
         );
       }
       
       result = { transactionId: newId };

    } else if (action === 'saveSettings') {
       // Sauvegarde des clés de l'API
       props.setProperty('PAYDUNYA_MASTER_KEY', data.payload.masterKey);
       props.setProperty('PAYDUNYA_PRIVATE_KEY', data.payload.privateKey);
       props.setProperty('PAYDUNYA_PUBLIC_KEY', data.payload.publicKey);
       props.setProperty('PAYDUNYA_TOKEN', data.payload.token);
       props.setProperty('PAYDUNYA_MODE', data.payload.mode);
       props.setProperty('PYTHON_SERVER_URL', data.payload.pythonUrl);

       // Synchronisation avec la feuille pour visibilité et persistance
       let sheet = ss.getSheetByName('Configuration');
       if (sheet) {
         const configData = [
           ['PAYDUNYA_MASTER_KEY', data.payload.masterKey],
           ['PAYDUNYA_PRIVATE_KEY', data.payload.privateKey],
           ['PAYDUNYA_PUBLIC_KEY', data.payload.publicKey],
           ['PAYDUNYA_TOKEN', data.payload.token],
           ['PAYDUNYA_MODE', data.payload.mode],
           ['PYTHON_SERVER_URL', data.payload.pythonUrl]
         ];
         sheet.getRange(2, 1, configData.length, 2).setValues(configData);
       }
       result = { success: true };

    } else if (action === 'updatePythonUrl') {
       // Met à jour uniquement l'URL du serveur Python (utile pour Ngrok automatique)
       props.setProperty('PYTHON_SERVER_URL', data.payload.pythonUrl);
       
       let sheet = ss.getSheetByName('Configuration');
       if (sheet) {
         const configData = sheet.getDataRange().getValues();
         for (let i = 1; i < configData.length; i++) {
           if (configData[i][0] === 'PYTHON_SERVER_URL') {
             sheet.getRange(i + 1, 2).setValue(data.payload.pythonUrl);
             break;
           }
         }
       }
       result = { success: true, message: "URL Python mise à jour" };

    } else if (action === 'getSettings') {
       // Récupère les paramètres actuels
       result = { 
         success: true, 
         settings: getPayDunyaConfig() || {}
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
                balance: parseFloat(rows[i][4]) || 0, 
                phone: rows[i][3].toString(),
                face_active: rows[i][8],
                face_url: faceUrl
              } 
            };
            break;
         }
       }

    } else if (action === 'initiatePayDunya') {
      const config = getPayDunyaConfig();
      const baseUrl = config.mode === "live" 
        ? "https://paydunya.com/api/v1/checkout-invoice/create" 
        : "https://paydunya.com/sandbox-api/v1/checkout-invoice/create";

      const amount = data.payload.amount;
      const phone = data.payload.phone;

      const payloadPayDunya = {
        "invoice": {
          "total_amount": amount,
          "description": "Recharge Wallet JEL DEM"
        },
        "store": {
          "name": "JEL DEM SHOP"
        },
        "custom_data": {
          "phone": phone
        },
        "actions": {
          "cancel_url": "https://jeldem.abmcy.com/",
          "return_url": "https://jeldem.abmcy.com/"
        }
      };

      const options = {
        "method": "post",
        "headers": {
          "PAYDUNYA-MASTER-KEY": config.masterKey,
          "PAYDUNYA-PRIVATE-KEY": config.privateKey,
          "PAYDUNYA-TOKEN": config.token,
          "Content-Type": "application/json"
        },
        "payload": JSON.stringify(payloadPayDunya),
        "muteHttpExceptions": true
      };

      const response = UrlFetchApp.fetch(baseUrl, options);
      const resData = JSON.parse(response.getContentText());

      if (resData.response_code === "00") {
        result = { success: true, url: resData.response_text };
      } else {
        result = { success: false, message: "Erreur PayDunya: " + resData.response_text };
      }

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
             sendStyledEmail(
               rows[i][2], 
               "Compte crédité avec succès", 
               "Confirmation de recharge", 
               `Votre compte JEL DEM vient d'être crédité de <b>${amount} FCFA</b> via PayDunya.<br><br>` +
               `Votre nouveau solde est de <b>${newBalance} FCFA</b>.`
             );
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

/**
 * Envoie un email stylisé HTML professionnel
 */
function sendStyledEmail(to, subject, title, message) {
  const htmlBody = `
    <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: auto; border: 1px solid #eee; border-radius: 12px; overflow: hidden;">
      <div style="background-color: #1a1a1a; padding: 25px; text-align: center;">
        <h1 style="color: #ffffff; margin: 0; font-size: 26px; font-weight: 800; letter-spacing: -1px;">
          JEL <span style="color: #f97316;">DEM</span>
        </h1>
      </div>
      <div style="padding: 40px; line-height: 1.6; color: #333; background-color: #ffffff;">
        <h2 style="color: #1a1a1a; margin-top: 0; font-size: 20px;">${title}</h2>
        <p style="font-size: 15px;">${message}</p>
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; font-size: 11px; color: #999; text-align: center;">
          Ceci est un message automatique de JEL DEM. Merci de ne pas y répondre directement.<br>
          <b>JEL DEM Shop & Go</b> - Dakar, Sénégal.
        </div>
      </div>
    </div>
  `;
  
  MailApp.sendEmail({
    to: to,
    subject: subject,
    htmlBody: htmlBody
  });
}

function doGet(e) {
  // Lancez l'URL du script dans le navigateur une fois pour initialiser
  setupDatabase();
  return HtmlService.createHtmlOutput("<h1>Systeme HYFLEX Initialise</h1><p>Les onglets ont ete crees dans votre Google Sheet.</p>");
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
      "PAYDUNYA-PUBLIC-KEY": config.publicKey,
      "PAYDUNYA-TOKEN": config.token,
      "Content-Type": "application/json"
    },
    "muteHttpExceptions": true
  };
  
  const response = UrlFetchApp.fetch(url, options);
  const content = response.getContentText();
  try {
    return JSON.parse(content);
  } catch (e) {
    console.error("Erreur parsing PayDunya: " + content);
    return { response_code: "99", response_text: "Réponse PayDunya invalide" };
  }
}
