// Nouveau code pour ESP32 DevKit - RFID MFRC522
#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

#define SS_PIN      5
#define RST_PIN     22
#define BUZZER_PIN  13
#define LED_OK      12  // Vert : Succès
#define LED_FAIL    14  // Rouge : Erreur
#define LED_STATUS  27  // Bleu : Transmission / WiFi

MFRC522 mfrc522(SS_PIN, RST_PIN);

const char* ssid = "VOTRE_WIFI";
const char* password = "VOTRE_PASSWORD";

// URL de votre serveur Python main.py
String serverUrl = "https://VOTRE_IP_LOCALE:8000/api/rfid_login";

void setup() {
  Serial.begin(115200);
  SPI.begin();
  mfrc522.PCD_Init();
  
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_OK, OUTPUT);
  pinMode(LED_FAIL, OUTPUT);
  pinMode(LED_STATUS, OUTPUT);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { 
    digitalWrite(LED_STATUS, !digitalRead(LED_STATUS)); // Clignote pendant la connexion
    delay(500); 
    Serial.print("."); 
  }
  Serial.println("\nConnecté au WiFi");
  digitalWrite(LED_STATUS, HIGH); // Allumé fixe quand connecté
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
  Serial.println("UID Badge: " + uid);

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_STATUS, LOW); // Indique l'envoi des données
    
    WiFiClientSecure client;
    client.setInsecure(); // Autorise le HTTPS auto-signé de main.py
    
    HTTPClient http;
    http.begin(client, serverUrl);
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");
    
    int httpResponseCode = http.POST("rfid_id=" + uid);
    
    if (httpResponseCode > 0) {
      String response = http.getString();
      if (response.indexOf("\"authorized\":true") > 0) {
        Serial.println("✅ ACCÈS ACCORDÉ - BIENVENUE");
        digitalWrite(LED_OK, HIGH);
        
        // Double bip de succès
        digitalWrite(BUZZER_PIN, HIGH); delay(80); digitalWrite(BUZZER_PIN, LOW); delay(50);
        digitalWrite(BUZZER_PIN, HIGH); delay(80); digitalWrite(BUZZER_PIN, LOW);
        
        delay(2000);
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
