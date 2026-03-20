/*
  ESP32 → Flask ML Training Dashboard
  ====================================
  Board: ESP32-CAM (AI-Thinker) or any ESP32 with OV2640 camera.
  Libraries required (install via Arduino Library Manager):
    - ArduinoJson  (>= 6.x)
    - Adafruit_MPU6050
    - DHT sensor library (Adafruit)
    - ESP32 Arduino core (board manager)

  Replace WIFI_SSID, WIFI_PASS, and SERVER_IP before flashing.
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_camera.h"          // only if camera is fitted
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>
#include <Wire.h>

// ── Configuration ──────────────────────────────────────
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_IP = "192.168.1.100";   // PC IP running Flask
const int   SERVER_PORT = 5000;

// ── Pin assignments ────────────────────────────────────
#define DHT_PIN     4
#define DHT_TYPE    DHT11
#define IR_PIN      34     // analog IR sensor output

// ── Timing ────────────────────────────────────────────
const unsigned long SENSOR_INTERVAL = 500;   // ms
const unsigned long NET_INTERVAL    = 1000;  // ms
unsigned long lastSensor = 0;
unsigned long lastNet    = 0;

// ── Objects ───────────────────────────────────────────
Adafruit_MPU6050 mpu;
DHT dht(DHT_PIN, DHT_TYPE);

// ─────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Wire.begin();
  dht.begin();
  pinMode(IR_PIN, INPUT);

  if (!mpu.begin()) {
    Serial.println("MPU6050 not found!");
  }

  // Connect to Wi-Fi
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print('.'); }
  Serial.println("\nConnected! IP: " + WiFi.localIP().toString());

  // Optional: init camera (ESP32-CAM)
  // camera_config_t config = { ... };
  // esp_camera_init(&config);
}

// ─────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // ── Send sensor data ──
  if (now - lastSensor >= SENSOR_INTERVAL) {
    lastSensor = now;
    sendSensorData();
  }

  // ── Send network parameters ──
  // In a real deployment this would come from actual packet capture.
  // For testing, dummy/computed values are sent here.
  if (now - lastNet >= NET_INTERVAL) {
    lastNet = now;
    sendNetworkParams();
  }
}

// ─────────────────────────────────────────────────────
void sendSensorData() {
  // Read MPU-6050
  sensors_event_t a, g, temp_mpu;
  mpu.getEvent(&a, &g, &temp_mpu);

  // Read DHT-11
  float humidity    = dht.readHumidity();
  float temperature = dht.readTemperature();

  // Read IR sensor
  int irRaw      = analogRead(IR_PIN);
  bool irDetected = (irRaw < 500);   // adjust threshold

  // Build JSON
  StaticJsonDocument<512> doc;
  doc["accel"]["x"] = a.acceleration.x;
  doc["accel"]["y"] = a.acceleration.y;
  doc["accel"]["z"] = a.acceleration.z;
  doc["gyro"]["x"]  = g.gyro.x;
  doc["gyro"]["y"]  = g.gyro.y;
  doc["gyro"]["z"]  = g.gyro.z;
  doc["temperature"] = isnan(temperature) ? 0 : temperature;
  doc["humidity"]    = isnan(humidity)    ? 0 : humidity;
  doc["ir"]["raw"]       = irRaw;
  doc["ir"]["detected"]  = irDetected;

  // Optionally attach a base64-encoded JPEG camera frame here:
  // doc["camera"] = captureFrameAsBase64();

  String body;
  serializeJson(doc, body);
  postJson("/api/sensor", body);
}

// ─────────────────────────────────────────────────────
void sendNetworkParams() {
  // Replace these with real computed values from your packet-sniffer logic.
  StaticJsonDocument<256> doc;
  doc["byte_rate"]            = random(1000, 9000);      // bytes/s
  doc["packet_rate"]          = random(10, 200);          // pkts/s
  doc["packet_size_variance"] = random(50, 5000);
  doc["time_gap_variance"]    = random(1, 500);
  doc["time_gap_mean"]        = random(1, 100);
  doc["packet_size_mean"]     = random(64, 1500);

  String body;
  serializeJson(doc, body);
  postJson("/api/network", body);
}

// ─────────────────────────────────────────────────────
void postJson(const char* endpoint, const String& body) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String("http://") + SERVER_IP + ":" + SERVER_PORT + endpoint;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  if (code < 0) {
    Serial.printf("HTTP POST failed (%s): %s\n", endpoint, http.errorToString(code).c_str());
  }
  http.end();
}
