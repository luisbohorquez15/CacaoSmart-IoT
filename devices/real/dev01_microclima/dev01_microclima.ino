/* =====================================================================
 *  CacaoSmart IoT - DEV-01  Nodo Microclima Lote 1  (dispositivo REAL)
 *  Hardware: ESP32 DevKit V1 + DHT22 (GPIO 4) + LDR/divisor 10k (GPIO 34) + LED (GPIO 2)
 *  Protocolo: MQTT 3.1.1 sobre TCP/IP (Wi-Fi), QoS 1 para comandos, LWT retenido
 *  Librerías: PubSubClient (Nick O'Leary), ArduinoJson 7, DHT sensor library (Adafruit)
 *
 *  Uplink   cacaosmart/santander/lote1/dev-01/telemetry   {ts, type, seq, temp_c, hr_pct, luz_lux, rssi_dbm, led}
 *  Shadow   cacaosmart/santander/lote1/dev-01/status      (retenido; ACK del último comando)
 *  Downlink cacaosmart/santander/lote1/dev-01/command
 *     {"cmd":"CALIBRATE","temp_offset":-0.8,"hr_offset":2,"interval_sec":10}
 *     {"cmd":"SET_INTERVAL","value":30}   {"cmd":"POWER","state":"off"}
 *     {"cmd":"LED","state":"on"}           {"cmd":"REBOOT"}   {"cmd":"PING"}
 * ===================================================================== */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <Preferences.h>
#include "time.h"

// ------------------------- CONFIGURACIÓN (editar) -------------------------
const char* WIFI_SSID    = "TU_WIFI";
const char* WIFI_PASS    = "TU_CLAVE_WIFI";
const char* MQTT_HOST    = "cacaosmart-iot.northcentralus.cloudapp.azure.com";  // dominio del despliegue
const uint16_t MQTT_PORT = 1883;
const char* MQTT_USER    = "device";
const char* MQTT_PASS    = "CLAVE_MQTT_DEVICE";
const char* DEVICE_ID    = "dev-01";          // = client-id (lo exige la ACL del broker)
// --------------------------------------------------------------------------

#define PIN_DHT 4
#define PIN_LDR 34
#define PIN_LED 2
const char* T_TELE = "cacaosmart/santander/lote1/dev-01/telemetry";
const char* T_STAT = "cacaosmart/santander/lote1/dev-01/status";
const char* T_CMD  = "cacaosmart/santander/lote1/dev-01/command";

DHT dht(PIN_DHT, DHT22);
WiFiClient net;
PubSubClient mqtt(net);
Preferences prefs;                    // la calibración sobrevive a reinicios (NVS flash)

float tempOffset = 0, hrOffset = 0, luxOffset = 0;
uint32_t intervalMs = 10000;
bool powerOn = true, led = false;
uint32_t seq = 0, lastPub = 0;
String lastCmd = "", lastSrc = "", lastMsg = "", lastCid = "";
bool lastOk = true;

String isoNow() {
  struct tm t;
  if (!getLocalTime(&t, 50)) return "";
  char b[25];
  strftime(b, sizeof(b), "%Y-%m-%dT%H:%M:%SZ", &t);
  return String(b);
}

float ldrToLux(int raw) {
  // LDR GL5528 con divisor de 10k a 3.3 V -> lux aproximado (curva log-log del fabricante)
  float v = raw * 3.3f / 4095.0f;
  if (v < 0.01f) v = 0.01f;
  float rLdr = 10000.0f * (3.3f - v) / v;
  return 500000.0f / pow(rLdr / 1000.0f, 1.25f) * 0.12f;
}

void publishStatus() {
  JsonDocument d;
  d["online"] = 1; d["device"] = DEVICE_ID; d["name"] = "Nodo microclima lote 1"; d["type"] = "real";
  d["power"] = powerOn ? "on" : "off"; d["interval_s"] = intervalMs / 1000; d["mode"] = "auto";
  d["offsets"]["temp_c"] = tempOffset; d["offsets"]["hr_pct"] = hrOffset; d["offsets"]["luz_lux"] = luxOffset;
  d["led"] = led ? 1 : 0; d["fw"] = "1.2.0"; d["ip"] = WiFi.localIP().toString(); d["ts"] = isoNow();
  if (lastCmd.length()) {
    JsonObject c = d["last_cmd"].to<JsonObject>();
    c["cid"] = lastCid; c["cmd"] = lastCmd; c["src"] = lastSrc; c["ok"] = lastOk ? 1 : 0; c["msg"] = lastMsg;
  }
  char buf[512];
  size_t n = serializeJson(d, buf);
  mqtt.publish(T_STAT, (uint8_t*)buf, n, true);       // retenido = "device shadow"
}

void savePrefs() {
  prefs.putFloat("tOff", tempOffset); prefs.putFloat("hOff", hrOffset); prefs.putFloat("lOff", luxOffset);
  prefs.putUInt("int", intervalMs);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) return;
  String cmd = d["cmd"] | "";
  cmd.toUpperCase();
  lastCmd = cmd; lastSrc = d["src"] | "desconocido"; lastCid = d["cid"] | ""; lastOk = true;

  if (cmd == "CALIBRATE") {
    if (d["temp_offset"].is<float>()) tempOffset = d["temp_offset"];
    if (d["hr_offset"].is<float>())   hrOffset   = d["hr_offset"];
    if (d["luz_offset"].is<float>())  luxOffset  = d["luz_offset"];
    if (d["interval_sec"].is<int>())  intervalMs = constrain((int)d["interval_sec"], 5, 60) * 1000UL;
    savePrefs();
    lastMsg = "calibrado (offset T=" + String(tempOffset, 2) + ")";
  } else if (cmd == "RESET_CALIBRATION") {
    tempOffset = hrOffset = luxOffset = 0; savePrefs(); lastMsg = "offsets borrados";
  } else if (cmd == "SET_INTERVAL") {
    intervalMs = constrain((int)(d["value"] | 10), 5, 60) * 1000UL; savePrefs();
    lastMsg = "intervalo = " + String(intervalMs / 1000) + "s";
  } else if (cmd == "POWER") {
    String s = d["state"] | "on"; powerOn = (s == "on");
    lastMsg = powerOn ? "telemetria encendida" : "telemetria apagada";
  } else if (cmd == "LED") {
    String s = d["state"] | "on"; led = (s == "on"); digitalWrite(PIN_LED, led);
    lastMsg = led ? "LED ON" : "LED OFF";
  } else if (cmd == "REBOOT") {
    lastMsg = "reiniciando..."; publishStatus(); mqtt.loop(); delay(300); ESP.restart();
  } else if (cmd == "PING") {
    lastMsg = "pong";
  } else {
    lastOk = false; lastMsg = "comando desconocido: " + cmd;
  }
  publishStatus();
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.printf("\nWi-Fi OK %s\n", WiFi.localIP().toString().c_str());
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // hora UTC para el timestamp ISO-8601
}

void connectMqtt() {
  while (!mqtt.connected()) {
    const char* will = "{\"online\":0,\"device\":\"dev-01\"}";
    if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS, T_STAT, 1, true, will)) {
      mqtt.subscribe(T_CMD, 1);
      publishStatus();
      Serial.println("MQTT conectado");
    } else {
      Serial.printf("MQTT rc=%d, reintento\n", mqtt.state());
      delay(3000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  analogReadResolution(12);
  dht.begin();
  prefs.begin("cacaosmart", false);
  tempOffset = prefs.getFloat("tOff", 0); hrOffset = prefs.getFloat("hOff", 0); luxOffset = prefs.getFloat("lOff", 0);
  intervalMs = prefs.getUInt("int", 10000);
  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(768);
  mqtt.setKeepAlive(30);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();
  if (powerOn && millis() - lastPub >= intervalMs) {
    lastPub = millis();
    float t = dht.readTemperature(), h = dht.readHumidity();
    if (isnan(t) || isnan(h)) { Serial.println("DHT22 sin lectura"); return; }
    int raw = 0;
    for (int i = 0; i < 8; i++) raw += analogRead(PIN_LDR);   // promedio anti-ruido
    raw /= 8;
    JsonDocument d;
    String ts = isoNow();
    if (ts.length()) d["ts"] = ts;
    d["type"] = "real"; d["seq"] = ++seq;
    d["temp_c"] = roundf((t + tempOffset) * 100) / 100.0;
    d["hr_pct"] = roundf((h + hrOffset) * 10) / 10.0;
    d["luz_lux"] = roundf(ldrToLux(raw) + luxOffset);
    d["rssi_dbm"] = WiFi.RSSI(); d["led"] = led ? 1 : 0;
    char buf[256];
    size_t n = serializeJson(d, buf);
    mqtt.publish(T_TELE, (uint8_t*)buf, n, false);
    Serial.println(buf);
  }
}
