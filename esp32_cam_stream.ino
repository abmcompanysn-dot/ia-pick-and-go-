#include "esp_camera.h"
#include <WiFi.h>
#include <WebSocketsClient.h>

const char* ssid = "VOTRE_WIFI";
const char* password = "VOTRE_MOT_DE_PASSE";
const char* server_ip = "VOTRE_IP_PC"; 

WebSocketsClient webSocket;

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5; config.pin_d1 = 18; config.pin_d2 = 19; config.pin_d3 = 21;
  config.pin_d4 = 36; config.pin_d5 = 39; config.pin_d6 = 34; config.pin_d7 = 35;
  config.pin_xclk = 0; config.pin_pclk = 22; config.pin_vsync = 25; config.pin_href = 23;
  config.pin_sscb_sda = 26; config.pin_sscb_scl = 27; config.pin_pwdn = 32; config.pin_reset = -1;
  config.xclk_freq_hz = 20000000; config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_QVGA; config.jpeg_quality = 12; config.fb_count = 1;

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
  delay(100);
}