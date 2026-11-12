/* =====================================================================
 *  CacaoSmart IoT - DEV-02  Nodo Suelo y Actuación  (dispositivo REAL)
 *  Hardware: ESP32 + sensor capacitivo de humedad v1.2 (GPIO 35) + módulo relé (GPIO 26,
 *            electroválvula 12 V o LED de demostración) + divisor 100k/100k a batería 18650 (GPIO 33)
 *  Protocolo: MQTT 3.1.1 sobre TCP/IP (Wi-Fi), QoS 1, LWT retenido
 *
 *  Uplink   cacaosmart/santander/lote1/dev-02/telemetry {humedad_suelo_pct, valvula, bateria_v, umbral_pct, rssi_dbm}
 *  Downlink cacaosmart/santander/lote1/dev-02/command
 *     {"cmd":"RELAY","state":"ON","duration_min":15}    {"cmd":"RELAY","state":"OFF"}
 *     {"cmd":"SET_THRESHOLD","value":35}                 {"cmd":"CALIBRATE","dry_raw":3050,"wet_raw":1250}
 *     {"cmd":"SET_MODE","value":"manual"}  (en manual el nodo ignora las órdenes automáticas src=rules)
 * ===================================================================== */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "time.h"

const char* WIFI_SSID    = "TU_WIFI";
const char* WIFI_PASS    = "TU_CLAVE_WIFI";
const char* MQTT_HOST    = "cacaosmart-iot.northcentralus.cloudapp.azure.com";
const uint16_t MQTT_PORT = 1883;
const char* MQTT_USER    = "device";
const char* MQTT_PASS    = "CLAVE_MQTT_DEVICE";
const char* DEVICE_ID    = "dev-02";

#define PIN_SOIL 35
#define PIN_RELAY 26
#define PIN_BAT 33
const char* T_TELE = "cacaosmart/santander/lote1/dev-02/telemetry";
const char* T_STAT = "cacaosmart/santander/lote1/dev-02/status";
const char* T_CMD  = "cacaosmart/santander/lote1/dev-02/command";

WiFiClient net;
PubSubClient mqtt(net);
Preferences prefs;
int dryRaw = 3050, wetRaw = 1250;     // calibración del sensor capacitivo (en aire / en agua)
float umbral = 35, soilOffset = 0;
uint32_t intervalMs = 10000, lastPub = 0, relayUntil = 0, seq = 0;
bool relay = false, powerOn = true, manual = false;
String lastCmd, lastSrc, lastMsg, lastCid;
bool lastOk = true;

String isoNow() {
  struct tm t;
  if (!getLocalTime(&t, 50)) return "";
  char b[25];
  strftime(b, sizeof(b), "%Y-%m-%dT%H:%M:%SZ", &t);
  return String(b);
}

void setRelay(bool on, uint32_t minutes) {
  relay = on;
  digitalWrite(PIN_RELAY, on ? HIGH : LOW);
  relayUntil = on ? millis() + minutes * 60000UL : 0;
}

void publishStatus() {
  JsonDocument d;
  d["online"] = 1; d["device"] = DEVICE_ID; d["name"] = "Nodo suelo y riego"; d["type"] = "real";
  d["power"] = powerOn ? "on" : "off"; d["interval_s"] = intervalMs / 1000; d["mode"] = manual ? "manual" : "auto";
  d["valvula"] = relay ? 1 : 0; d["umbral_pct"] = umbral; d["dry_raw"] = dryRaw; d["wet_raw"] = wetRaw;
  d["offsets"]["humedad_suelo_pct"] = soilOffset; d["fw"] = "1.2.0"; d["ts"] = isoNow();
  if (lastCmd.length()) {
    JsonObject c = d["last_cmd"].to<JsonObject>();
    c["cid"] = lastCid; c["cmd"] = lastCmd; c["src"] = lastSrc; c["ok"] = lastOk ? 1 : 0; c["msg"] = lastMsg;
  }
  char buf[512];
  size_t n = serializeJson(d, buf);
  mqtt.publish(T_STAT, (uint8_t*)buf, n, true);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument d;
  if (deserializeJson(d, payload, len)) return;
  String cmd = d["cmd"] | "";
  cmd.toUpperCase();
  lastCmd = cmd; lastSrc = d["src"] | "desconocido"; lastCid = d["cid"] | ""; lastOk = true;
  bool fromRules = (lastSrc == "rules");

  if (cmd == "RELAY" || cmd == "RIEGO") {
    String s = d["state"] | "ON";
    s.toUpperCase();
    if (s == "ON" && manual && fromRules) {
      lastOk = false; lastMsg = "modo manual: se ignora la regla";
    } else {
      uint32_t m = d["duration_min"] | 15;
      setRelay(s == "ON", m);
      lastMsg = relay ? "rele ON " + String(m) + " min" : "rele OFF";
    }
  } else if (cmd == "SET_THRESHOLD") {
    umbral = constrain((float)(d["value"] | 35.0), 10.0f, 60.0f);
    prefs.putFloat("umbral", umbral);
    lastMsg = "umbral " + String(umbral, 0) + "%";
  } else if (cmd == "CALIBRATE") {
    if (d["dry_raw"].is<int>()) dryRaw = d["dry_raw"];
    if (d["wet_raw"].is<int>()) wetRaw = d["wet_raw"];
    if (d["humedad_suelo_pct_offset"].is<float>()) soilOffset = d["humedad_suelo_pct_offset"];
    if (d["interval_sec"].is<int>()) intervalMs = constrain((int)d["interval_sec"], 5, 60) * 1000UL;
    prefs.putInt("dry", dryRaw); prefs.putInt("wet", wetRaw); prefs.putFloat("sOff", soilOffset);
    lastMsg = "calibrado seco=" + String(dryRaw) + " humedo=" + String(wetRaw);
  } else if (cmd == "SET_INTERVAL") {
    intervalMs = constrain((int)(d["value"] | 10), 5, 60) * 1000UL;
    lastMsg = "intervalo " + String(intervalMs / 1000) + "s";
  } else if (cmd == "SET_MODE") {
    String m = d["value"] | "auto"; manual = (m == "manual"); lastMsg = "modo " + m;
  } else if (cmd == "POWER") {
    String s = d["state"] | "on"; powerOn = (s == "on"); lastMsg = powerOn ? "telemetria ON" : "telemetria OFF";
  } else if (cmd == "REBOOT") {
    lastMsg = "reiniciando"; publishStatus(); mqtt.loop(); delay(300); ESP.restart();
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
  while (WiFi.status() != WL_CONNECTED) delay(400);
  configTime(0, 0, "pool.ntp.org");
}

void connectMqtt() {
  while (!mqtt.connected()) {
    if (mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS, T_STAT, 1, true, "{\"online\":0,\"device\":\"dev-02\"}")) {
      mqtt.subscribe(T_CMD, 1);
      publishStatus();
    } else {
      delay(3000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RELAY, OUTPUT);
  setRelay(false, 0);
  analogReadResolution(12);
  prefs.begin("cacaosmart", false);
  dryRaw = prefs.getInt("dry", 3050); wetRaw = prefs.getInt("wet", 1250);
  umbral = prefs.getFloat("umbral", 35); soilOffset = prefs.getFloat("sOff", 0);
  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(768);
  mqtt.setCallback(onMessage);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();
  if (relay && relayUntil && (int32_t)(millis() - relayUntil) >= 0) {   // fin del riego temporizado (edge)
    setRelay(false, 0);
    lastCmd = "AUTO_OFF"; lastSrc = "edge"; lastMsg = "riego finalizado"; lastOk = true;
    publishStatus();
  }
  if (powerOn && millis() - lastPub >= intervalMs) {
    lastPub = millis();
    long raw = 0;
    for (int i = 0; i < 16; i++) raw += analogRead(PIN_SOIL);
    raw /= 16;
    float pct = constrain(100.0f * (dryRaw - raw) / (float)(dryRaw - wetRaw), 0.0f, 100.0f) + soilOffset;
    float vbat = analogReadMilliVolts(PIN_BAT) * 2.0f / 1000.0f;
    JsonDocument d;
    String ts = isoNow();
    if (ts.length()) d["ts"] = ts;
    d["type"] = "real"; d["seq"] = ++seq;
    d["humedad_suelo_pct"] = roundf(pct * 10) / 10.0; d["valvula"] = relay ? 1 : 0;
    d["bateria_v"] = roundf(vbat * 1000) / 1000.0; d["umbral_pct"] = umbral; d["rssi_dbm"] = WiFi.RSSI();
    char buf[256];
    size_t n = serializeJson(d, buf);
    mqtt.publish(T_TELE, (uint8_t*)buf, n, false);
  }
}
