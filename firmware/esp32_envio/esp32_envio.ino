/*
  ESP32 -> API de sensores (POST JSON).  Firmware para las pruebas de integración.

  - Muestrea cada INTERVALO_MS (DHT real o valores simulados según USE_DHT).
  - Cada muestra recibe un `seq` único y persistente (NVS): un reintento repite el mismo seq y la
    API lo trata como duplicado (200) en vez de guardarlo dos veces.
  - Cola en RAM (COLA_MAX): si no hay WiFi/API, las muestras se acumulan y se envían luego en lotes
    (/api/v1/lecturas/batch) con backoff exponencial. Si la cola se llena se descarta la más antigua.
  - Hora por NTP: `ts_dispositivo` se envía solo si el reloj ya está sincronizado.

  Configuración: copiar config.h.example a config.h y completar. Requiere el core "esp32" de Espressif.
  Con USE_DHT=1 instalar la librería "DHT sensor library" (Adafruit) y "Adafruit Unified Sensor".
  Estado: SIN COMPILAR en el entorno de desarrollo; compilar y probar en el Arduino IDE.
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <time.h>
#include "config.h"

#if USE_HTTPS
#include <WiFiClientSecure.h>
#endif
#if USE_DHT
#include <DHT.h>
DHT dht(DHT_PIN, DHT_TYPE);
#endif

// ---------- Parámetros internos ----------
const int COLA_MAX = 60;                 // muestras en RAM (60 x 10 s = 10 min sin red)
const int LOTE_MAX = 10;                 // muestras por petición /batch
const uint32_t SEQ_MARGEN = 20;          // el seq se guarda en NVS cada 20 muestras; al arrancar se salta ese margen
const time_t HORA_VALIDA = 1700000000;   // cualquier epoch menor => NTP aún no sincronizó

struct Muestra {
  uint32_t seq;
  time_t ts;
  float temp;
  float hum;
  int8_t rssi;
};

Muestra cola[COLA_MAX];
int colaIni = 0, colaN = 0;
uint32_t perdidas = 0;                   // muestras descartadas por cola llena o rechazo 4xx
uint32_t seq = 0;
Preferences prefs;

unsigned long ultMuestra = 0, ultWiFi = 0, proximoEnvio = 0, esperaEnvio = 2000;
bool soloIndividual = false;             // tras un rechazo de lote se envía de a una para aislar la muestra mala

// ---------- WiFi ----------
void onWiFiEvent(arduino_event_id_t event, arduino_event_info_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    Serial.printf("[WiFi] desconectado, motivo %u\n", info.wifi_sta_disconnected.reason);
  } else if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    Serial.print("[WiFi] IP: ");
    Serial.println(WiFi.localIP());
  }
}

void iniciarWiFi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  WiFi.onEvent(onWiFiEvent);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(250);
}

void vigilarWiFi() {
  if (WiFi.status() == WL_CONNECTED) { ultWiFi = millis(); return; }
  if (millis() - ultWiFi > 30000) {      // 30 s sin conexión: reinicia el intento
    Serial.println("[WiFi] sin conexión, reiniciando intento");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    ultWiFi = millis();
  }
}

// ---------- Hora ----------
bool horaLista() { return time(nullptr) > HORA_VALIDA; }

// ---------- Sensor ----------
bool leerSensor(float &t, float &h) {
#if USE_DHT
  h = dht.readHumidity();
  t = dht.readTemperature();
  return !(isnan(t) || isnan(h));        // lectura fallida: no se envía (se registra en el monitor serie)
#else
  static float st = 22.0, sh = 50.0;     // caminata aleatoria para simular un sensor
  st += random(-30, 31) / 100.0;
  sh += random(-100, 101) / 100.0;
  sh = constrain(sh, 0.0, 100.0);
  t = st;
  h = sh;
  return true;
#endif
}

// ---------- Cola ----------
void encolar(const Muestra &m) {
  if (colaN == COLA_MAX) {               // llena: descarta la más antigua
    colaIni = (colaIni + 1) % COLA_MAX;
    colaN--;
    perdidas++;
  }
  cola[(colaIni + colaN) % COLA_MAX] = m;
  colaN++;
}

void desencolar(int n) {
  colaIni = (colaIni + n) % COLA_MAX;
  colaN -= n;
}

// ---------- JSON / HTTP ----------
void jsonLectura(const Muestra &m, String &out) {
  char ts[32] = "";
  if (m.ts > HORA_VALIDA) {
    struct tm tmv;
    gmtime_r(&m.ts, &tmv);
    char f[24];
    strftime(f, sizeof(f), "%Y-%m-%dT%H:%M:%SZ", &tmv);
    snprintf(ts, sizeof(ts), "\"ts_dispositivo\":\"%s\",", f);
  }
  char buf[384];
  snprintf(buf, sizeof(buf),
           "{\"device_id\":\"%s\",\"seq\":%lu,%s\"rssi\":%d,\"fw_version\":\"%s\",\"ubicacion\":\"%s\","
           "\"mediciones\":[{\"magnitud\":\"temperatura\",\"valor\":%.1f,\"unidad\":\"C\"},"
           "{\"magnitud\":\"humedad\",\"valor\":%.1f,\"unidad\":\"%%\"}]}",
           DEVICE_ID, (unsigned long)m.seq, ts, m.rssi, FW_VERSION, UBICACION, m.temp, m.hum);
  out += buf;
}

int postJson(const char *path, const String &body) {
  HTTPClient http;
#if USE_HTTPS
  WiFiClientSecure client;
  client.setInsecure();                  // SOLO pruebas: no valida el certificado
  http.begin(client, API_HOST, API_PORT, path, true);
#else
  WiFiClient client;
  http.begin(client, API_HOST, API_PORT, path);
#endif
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int code = http.POST(body);            // <0 = error de red/timeout
  http.end();
  return code;
}

void vaciarCola() {
  if (colaN == 0 || WiFi.status() != WL_CONNECTED || (long)(millis() - proximoEnvio) < 0) return;

  int n = soloIndividual ? 1 : min(colaN, LOTE_MAX);
  int code;
  String body;
  if (n == 1) {
    jsonLectura(cola[colaIni], body);
    code = postJson("/api/v1/lecturas", body);
  } else {
    body = "{\"lecturas\":[";
    for (int i = 0; i < n; i++) {
      if (i) body += ',';
      jsonLectura(cola[(colaIni + i) % COLA_MAX], body);
    }
    body += "]}";
    code = postJson("/api/v1/lecturas/batch", body);
  }

  if (code == 200 || code == 201) {
    Serial.printf("[API] %d OK (%d muestra/s, pendientes %d)\n", code, n, colaN - n);
    desencolar(n);
    esperaEnvio = 2000;
    proximoEnvio = 0;
    soloIndividual = false;
  } else if (code == 400 || code == 413 || code == 422) {
    if (n > 1) {                         // aislar la muestra rechazada enviando de a una
      Serial.printf("[API] lote rechazado (%d), se reintenta individual\n", code);
      soloIndividual = true;
    } else {
      Serial.printf("[API] muestra rechazada (%d), se descarta seq=%lu\n", code, (unsigned long)cola[colaIni].seq);
      desencolar(1);
      perdidas++;
    }
  } else {                               // 401, 5xx, timeout, sin ruta: conservar y reintentar con backoff
    esperaEnvio = min(esperaEnvio * 2, 60000UL);
    proximoEnvio = millis() + esperaEnvio;
    Serial.printf("[API] fallo %d (%s), reintento en %lu s\n", code,
                  code < 0 ? HTTPClient::errorToString(code).c_str() : "respuesta HTTP", esperaEnvio / 1000);
  }
}

// ---------- Arduino ----------
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== ESP32 -> API de sensores ===");

  prefs.begin("envio", false);
  seq = prefs.getUInt("seq", 0) + SEQ_MARGEN;   // salta un margen: tras un reinicio no se reutilizan seq
  prefs.putUInt("seq", seq);
  Serial.printf("[SEQ] inicio en %lu\n", (unsigned long)seq);

#if USE_DHT
  dht.begin();
#endif
  iniciarWiFi();
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  ultWiFi = millis();
}

void loop() {
  vigilarWiFi();

  if (millis() - ultMuestra >= INTERVALO_MS) {
    ultMuestra = millis();
    float t, h;
    if (leerSensor(t, h)) {
      Muestra m = {seq++, horaLista() ? time(nullptr) : 0, t, h, (int8_t)WiFi.RSSI()};
      if (seq % SEQ_MARGEN == 0) prefs.putUInt("seq", seq);
      encolar(m);
      Serial.printf("[MUESTRA] seq=%lu T=%.1f C H=%.1f %% cola=%d perdidas=%lu hora=%s\n",
                    (unsigned long)m.seq, t, h, colaN, (unsigned long)perdidas, m.ts ? "NTP" : "sin NTP");
    } else {
      Serial.println("[SENSOR] lectura inválida (NaN), muestra omitida");
    }
  }

  vaciarCola();
  delay(10);
}
