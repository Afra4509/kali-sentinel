/*
 * jagakali_node.ino  (ESP32, Arduino IDE)
 * Satu node Jagakali: baca 5 sensor, kirim JSON ke MQTT tiap 60 detik.
 * Untuk node kedua cukup ganti NODE_ID menjadi "HILIR".
 *
 * Library (Library Manager): PubSubClient (Nick O'Leary), ArduinoJson (v7),
 *                            OneWire, DallasTemperature
 *
 * Contoh pesan yang dikirim ke jagakali/node/HULU:
 * {"node_id":"HULU","timestamp":"2026-12-01T10:15:00+07:00","ph":7.1,"temperature_c":28.4,
 *  "turbidity_ntu":42.0,"tds_ppm_est":210,"water_level_cm":85.0,"rssi":-61}
 *
 * Kalibrasi di bawah adalah contoh; WAJIB diganti dengan hasil kalibrasi alat tim
 * (larutan buffer pH 4/7, larutan TDS standar, tinggi pemasangan sensor jarak).
 */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <time.h>

// ---------- ubah bagian ini ----------
const char* WIFI_SSID   = "NAMA_WIFI";
const char* WIFI_PASS   = "PASSWORD_WIFI";
const char* NODE_ID     = "HULU";                 // "HULU" atau "HILIR"
#ifndef JAGAKALI_MQTT_HOST
#define JAGAKALI_MQTT_HOST "192.168.1.10"  // Ganti dengan IP LAN/VPN host Docker
#endif
const char* MQTT_HOST = JAGAKALI_MQTT_HOST;
const uint16_t MQTT_PORT = 1883;                  // ESP32 memakai TCP biasa, bukan WebSocket
const uint32_t INTERVAL_MS = 60000;               // 60 detik; untuk simulasi video boleh 5000

// pin
const int PIN_PH        = 34;   // ADC1 (ADC2 tidak bisa dipakai saat WiFi aktif)
const int PIN_TURBIDITY = 35;
const int PIN_TDS       = 32;
const int PIN_DS18B20   = 4;
const int PIN_TRIG      = 5;    // sensor jarak tahan air (mis. JSN-SR04T) dipasang menghadap air
const int PIN_ECHO      = 18;

// kalibrasi (CONTOH, ganti!)
const float PH_SLOPE      = -5.70;   // pH per volt, dari buffer pH 4 dan 7
const float PH_OFFSET     = 21.34;
const float SENSOR_HEIGHT_CM = 200.0; // jarak sensor ke dasar referensi (titik nol tinggi air)
// -------------------------------------

WiFiClient net;
PubSubClient mqtt(net);
OneWire oneWire(PIN_DS18B20);
DallasTemperature ds(&oneWire);
char topic[48];

float readVolt(int pin, int n = 30) {
  // rata-rata median sederhana agar tidak terganggu lonjakan
  int v[30];
  for (int i = 0; i < n; i++) { v[i] = analogReadMilliVolts(pin); delay(10); }
  for (int i = 0; i < n - 1; i++) for (int j = i + 1; j < n; j++) if (v[j] < v[i]) { int t = v[i]; v[i] = v[j]; v[j] = t; }
  long s = 0; for (int i = 5; i < n - 5; i++) s += v[i];
  return s / float(n - 10) / 1000.0;
}

float readTemperature() {
  ds.requestTemperatures();
  return ds.getTempCByIndex(0);           // -127 berarti sensor terputus; dashboard menandai "Sensor error"
}

float readPH() { return PH_SLOPE * readVolt(PIN_PH) + PH_OFFSET; }

float readTurbidity() {
  // rumus umum modul turbidity analog 5V lewat pembagi tegangan; kalibrasi dengan larutan standar NTU
  float v = readVolt(PIN_TURBIDITY) * 1.5;  // kembalikan ke skala 5V bila memakai pembagi 2/3
  float ntu = -1120.4 * v * v + 5742.3 * v - 4352.9;
  return ntu < 0 ? 0 : ntu;
}

float readTDS(float tempC) {
  float v = readVolt(PIN_TDS);
  float comp = 1.0 + 0.02 * (tempC - 25.0);            // kompensasi suhu
  float cv = v / comp;
  float tds = (133.42 * cv * cv * cv - 255.86 * cv * cv + 857.39 * cv) * 0.5;
  return tds > 1000 ? 1000 : tds;                      // sensor jenuh di 1000 ppm
}

float readWaterLevel() {
  digitalWrite(PIN_TRIG, LOW); delayMicroseconds(4);
  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(20);
  digitalWrite(PIN_TRIG, LOW);
  long us = pulseIn(PIN_ECHO, HIGH, 30000);
  if (us == 0) return NAN;
  float dist = us * 0.0343 / 2.0;                      // cm
  return SENSOR_HEIGHT_CM - dist;                      // makin dekat permukaan = makin tinggi air
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
  configTime(7 * 3600, 0, "pool.ntp.org", "time.google.com");   // WIB = UTC+7
}

void connectMQTT() {
  while (!mqtt.connected()) {
    String id = String("ks-") + NODE_ID + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    if (mqtt.connect(id.c_str())) Serial.println("MQTT terhubung");
    else { Serial.printf("MQTT gagal rc=%d, ulang 3 detik\n", mqtt.state()); delay(3000); }
  }
}

String isoNow() {
  struct tm t;
  if (!getLocalTime(&t, 2000)) return "";
  char buf[32];
  strftime(buf, sizeof buf, "%Y-%m-%dT%H:%M:%S+07:00", &t);
  return String(buf);
}

void setup() {
  Serial.begin(115200);
  analogSetAttenuation(ADC_11db);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  ds.begin();
  snprintf(topic, sizeof topic, "jagakali/node/%s", NODE_ID);
  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  static uint32_t last = 0;
  if (millis() - last < INTERVAL_MS && last != 0) return;
  last = millis();

  float temp = readTemperature();
  JsonDocument doc;
  doc["node_id"] = NODE_ID;
  doc["timestamp"] = isoNow();
  doc["ph"] = round(readPH() * 100) / 100.0;
  doc["temperature_c"] = round(temp * 100) / 100.0;
  doc["turbidity_ntu"] = round(readTurbidity() * 10) / 10.0;
  doc["tds_ppm_est"] = (int)round(readTDS(temp > -100 ? temp : 25.0));
  float lvl = readWaterLevel();
  if (isnan(lvl)) doc["water_level_cm"] = nullptr; else doc["water_level_cm"] = round(lvl * 10) / 10.0;
  doc["rssi"] = WiFi.RSSI();

  char out[384];
  size_t n = serializeJson(doc, out);
  bool ok = mqtt.publish(topic, out, n);
  Serial.printf("%s %s\n", ok ? "terkirim" : "GAGAL", out);
}
