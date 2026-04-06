// ESP32-CAM vers Python Server
#include "esp_camera.h"
#include <WiFi.h>
#include <WebSocketsClient.h>

const char* ssid = "VOTRE_WIFI";
const char* password = "VOTRE_PASSWORD";
const char* server_ip = "192.168.1.XX"; // IP de votre PC

WebSocketsClient webSocket;

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
  
  // Config Caméra (AI-Thinker)
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5; config.pin_d1 = 18; // ... (config standard AI-Thinker)
  esp_camera_init(&config);
  
  webSocket.begin(server_ip, 8000, "/ws/cam_esp32");
}

void loop() {
  webSocket.loop();
  camera_fb_t * fb = esp_camera_fb_get();
  if (fb) {
    webSocket.sendBIN(fb->buf, fb->len);
    esp_camera_fb_return(fb);
  }
  delay(50); // ~20 FPS
}
