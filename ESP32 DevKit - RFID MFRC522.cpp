// Nouveau code pour ESP32 DevKit - RFID MFRC522
#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// --- CABLAGE RFID MFRC522 ---
#define SS_PIN      5   // SDA    
#define RST_PIN     22  // RST
// Pins SPI standards sur ESP32 (VSPI) :
// SCK  -> GPIO 18
// MOSI -> GPIO 23
// MISO -> GPIO 19

// --- ALERTES ET STATUS ---
#define BUZZER_PIN  13
#define LED_OK      12  // Vert : Succès
#define LED_FAIL    14  // Rouge : Erreur
#define LED_STATUS  27  // Bleu : Transmission / WiFi
#define RELAY_PIN   4   // Sortie pour Gâche électrique / Relais

MFRC522 mfrc522(SS_PIN, RST_PIN);

const char* ssid = "abmcy";
const char* password = "test1234v";

// URL directe vers votre déploiement Google Apps Script
String serverUrl = "https://script.google.com/macros/s/AKfycbxxSOZyptRBlGr0svsXlWzjANkMK8RRz03gVizG56nS6KsIfyVW0ghuyxonCY7ebqYGjQ/exec";

void setup() {
  Serial.begin(115200); // Vérifie bien que ton moniteur série est réglé sur 115200
  delay(1000);
  Serial.println("\n======================================");
  Serial.println("   DEMARRAGE DU TERMINAL JEL DEM");
  Serial.println("======================================");

  // Diagnostic de la mémoire vive (RAM) interne
  Serial.print("Mémoire Heap libre : ");
  Serial.print(ESP.getFreeHeap() / 1024);
  Serial.println(" KB");

  SPI.begin();
  mfrc522.PCD_Init();
  
  // Diagnostic du lecteur RFID
  Serial.print("Vérification du lecteur RFID... ");
  byte v = mfrc522.PCD_ReadRegister(mfrc522.VersionReg);
  if (v == 0 || v == 0xFF) Serial.println("ERREUR : Lecteur non trouvé !");
  else Serial.println("Lecteur trouvé ! Version: 0x" + String(v, HEX));

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_OK, OUTPUT);
  pinMode(LED_FAIL, OUTPUT);
  pinMode(LED_STATUS, OUTPUT);
  pinMode(RELAY_PIN, OUTPUT); digitalWrite(RELAY_PIN, LOW);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { 
    digitalWrite(LED_STATUS, !digitalRead(LED_STATUS)); // Clignote pendant la connexion
    delay(500); 
    Serial.print("."); 
  }
  Serial.println("\nConnecté au WiFi");
  digitalWrite(LED_STATUS, HIGH); // Allumé fixe quand connecté
  Serial.println("En attente d'une carte...");
}

void loop() {
  if ( ! mfrc522.PICC_IsNewCardPresent()) return;
  if ( ! mfrc522.PICC_ReadCardSerial()) return;

  // Bip court pour confirmer la lecture physique
  digitalWrite(BUZZER_PIN, HIGH);
  delay(100);
  digitalWrite(BUZZER_PIN, LOW);

  String uid = "";
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    uid += String(mfrc522.uid.uidByte[i] < 0x10 ? "0" : "");
    uid += String(mfrc522.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  Serial.println("\n--- NOUVELLE CARTE DÉTECTÉE ---");
  Serial.println("N° UID : " + uid);
  
  MFRC522::PICC_Type piccType = mfrc522.PICC_GetType(mfrc522.uid.sak);
  Serial.println("Type   : " + String(mfrc522.PICC_GetTypeName(piccType)));

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_STATUS, LOW); // Indique l'envoi des données
    
    WiFiClientSecure client;
    client.setInsecure(); 
    

    
    HTTPClient http;
    http.begin(client, serverUrl);
    http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS); 
    http.addHeader("Content-Type", "application/json");
    http.addHeader("User-Agent", "ESP32-JelDem"); 
    
    // Préparation du payload JSON attendu par votre Apps Script
    String jsonPayload = "{\"action\":\"requestDoorAccess\", \"data\":{\"rfidId\":\"" + uid + "\"}}";
    
    int httpResponseCode = http.POST(jsonPayload);
    
    if (httpResponseCode > 0) {
      String response = http.getString();
      Serial.println("\n--- RÉPONSE GOOGLE ---");
      Serial.println(response);

      DynamicJsonDocument doc(1024);
      DeserializationError error = deserializeJson(doc, response);

      if (!error && doc["authorized"] == true) {
        const char* name = doc["user_data"]["name"] | "Utilisateur";
        long balance = doc["user_data"]["balance"] | 0;

        Serial.printf("✅ ACCÈS ACCORDÉ - BIENVENUE %s\n", name);
        Serial.printf("💰 SOLDE RESTANT : %ld FCFA\n", balance);

        digitalWrite(LED_OK, HIGH);
        digitalWrite(RELAY_PIN, HIGH); // Ouvre la porte
        
        // Double bip de succès
        digitalWrite(BUZZER_PIN, HIGH); delay(80); digitalWrite(BUZZER_PIN, LOW); delay(50);
        digitalWrite(BUZZER_PIN, HIGH); delay(80); digitalWrite(BUZZER_PIN, LOW);
        
        delay(3000); // Temps d'ouverture de la porte
        
        digitalWrite(RELAY_PIN, LOW); // Referme la porte
        digitalWrite(LED_OK, LOW);
      } else {
        Serial.println("❌ ACCÈS REFUSÉ");
        digitalWrite(LED_FAIL, HIGH);
        
        // Un seul bip long d'erreur
        digitalWrite(BUZZER_PIN, HIGH); delay(600); digitalWrite(BUZZER_PIN, LOW);
        
        delay(2000);
        digitalWrite(LED_FAIL, LOW);
      }
    }
    http.end();
    digitalWrite(LED_STATUS, HIGH);
  }
}
