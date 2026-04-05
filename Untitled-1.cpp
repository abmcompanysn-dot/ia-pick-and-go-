#include <Arduino.h>
#include <WiFi.h>
#include <SPI.h>
#include <MFRC522.h>

/// --- CONFIGURATION WI-FI ---
const char* ssid = "abmcy";      // <-- Mettre votre WiFi
const char* password = "test1234v"; // <-- Mettre le mot de passe

// --- CONFIGURATION SERVEUR ---
String serverName = "192.168.1.11"; // <-- Mettre VOTRE adresse IP (trouvée avec ipconfig)
String rfidPath = "/api/rfid_login"; 
int serverPort = 8000;

// --- PINS RFID RC522 (Standard ESP32 DevKit) ---
// SDA: 5, SCK: 18, MOSI: 23, MISO: 19, RST: 22
#define SS_PIN  5
#define RST_PIN 22
MFRC522 mfrc522(SS_PIN, RST_PIN);

// --- PIN RELAIS (Exemple : GPIO 4) ---
#define RELAY_PIN 4

// --- PINS LEDs STATUT ---
#define LED_CONN 2    // Bleu : Statut Connexion
#define LED_LOCKED 15 // Rouge : Fermé / Refusé
#define LED_OPEN 14   // Vert : Ouvert / Autorisé

WiFiClient client;

void setup() {
  Serial.begin(115200);

  // Init LEDs
  pinMode(LED_CONN, OUTPUT);
  pinMode(LED_LOCKED, OUTPUT);
  pinMode(LED_OPEN, OUTPUT);
  digitalWrite(LED_LOCKED, HIGH); // Par défaut fermé

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_CONN, !digitalRead(LED_CONN)); // Clignote pendant connexion
  }
  Serial.println("\nWiFi connecté");
  digitalWrite(LED_CONN, HIGH); // Fixe si connecté

  // Init RFID
  SPI.begin();
  mfrc522.PCD_Init();

  // Init du relais
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  Serial.println("JEL DEM - Terminal RFID Prêt");
}

void loop() {
  // --- DÉTECTION RFID ---
  if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
    String uid = "";
    for (byte i = 0; i < mfrc522.uid.size; i++) {
      uid += String(mfrc522.uid.uidByte[i] < 0x10 ? "0" : "");
      uid += String(mfrc522.uid.uidByte[i], HEX);
    }
    Serial.println("Carte détectée : " + uid);
    
    // Envoyer l'UID au serveur pour loguer l'utilisateur
    if (client.connect(serverName.c_str(), serverPort)) {
      client.println("POST " + rfidPath + " HTTP/1.1");
      client.println("Host: " + serverName);
      client.println("Content-Type: application/x-www-form-urlencoded");
      client.print("Content-Length: ");
      client.println(uid.length() + 8);
      client.println();
      client.print("rfid_id=" + uid);

      // Lecture de la réponse JSON du serveur
      while (client.connected()) {
        String line = client.readStringUntil('\n');
        if (line == "\r") break;
      }
      String response = client.readString();
      if (response.indexOf("\"authorized\":true") != -1) {
        Serial.println("ACCÈS AUTORISÉ PAR JEL DEM");
        digitalWrite(RELAY_PIN, HIGH);
        delay(3000);
        digitalWrite(RELAY_PIN, LOW);
      } else {
        Serial.println("ACCÈS REFUSÉ");
      }
      client.stop();
    }
    
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
  }
  
  delay(100); // Petite pause pour la stabilité du processeur
}
