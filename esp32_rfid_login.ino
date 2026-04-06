#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <HTTPClient.h>

#define SS_PIN  5
#define RST_PIN 22
MFRC522 rfid(SS_PIN, RST_PIN);

const char* ssid = "VOTRE_WIFI";
const char* password = "VOTRE_MOT_DE_PASSE";
const char* serverUrl = "https://VOTRE_IP_SERVEUR:8000/api/rfid_login";

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  SPI.begin();
  rfid.PCD_Init();
  Serial.println("Système RFID Prêt...");
}

void loop() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;

  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    uid += String(rfid.uid.uidByte[i] < 0x10 ? "0" : "");
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  Serial.println("Badge détecté : " + uid);

  HTTPClient http;
  http.begin(serverUrl);
  http.addHeader("Content-Type", "application/x-www-form-urlencoded");
  
  int httpResponseCode = http.POST("rfid_id=" + uid);
  if (httpResponseCode > 0) {
    String response = http.getString();
    if (response.indexOf("success") > 0) {
      Serial.println("✅ ACCÈS ACCORDÉ");
    } else {
      Serial.println("❌ ACCÈS REFUSÉ");
    }
  }
  http.end();
  rfid.PICC_HaltA();
  delay(2000);
}