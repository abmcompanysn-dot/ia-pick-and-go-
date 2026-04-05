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
    'Utilisateurs': ['ID_Utilisateur', 'Nom', 'Email', 'Telephone', 'Solde_FCFA', 'Date_Inscription', 'Mot_de_Passe', 'RFID_ID', 'Face_ID_Active'],
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
             const tRows = transSheet.getDataRange().getValues(); // Fix: Was not retrieving transactions for RFID login
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
             user_data: { name: rows[i][1], balance: rows[i][4], phone: rows[i][3], face_id: rows[i][8], transactions: transactions } 
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

    } else if (action === 'uploadImage') {
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
