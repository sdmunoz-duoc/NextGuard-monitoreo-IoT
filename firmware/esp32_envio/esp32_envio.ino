/*
  ESP32 -> API de sensores (POST JSON).  Sensor DHT11 + MQ135, portal cautivo, cola con reintentos.

  Primer encendido (sin configuración guardada) o tras mantener BOOT 3 s al encender:
    1. El ESP32 crea la red WiFi SENSOR-XXXX.
    2. Conecta el celular a esa red: se abre el portal (http://192.168.4.1).
    3. Completa WiFi, servidor, API key, cliente, nombre del sensor, ubicación y ciclo -> Guardar.
    4. Guarda todo en la flash (Preferences) y reinicia conectado a la red indicada.

  En operación: lee los sensores cada `ciclo` segundos, asigna un `seq` único y persistente (NVS) y envía
  POST /api/v1/lecturas. Un reintento repite el mismo seq y la API responde 200 {duplicado} sin guardar dos veces.
  Si no hay WiFi/API las muestras esperan en una cola en RAM y se envían después en lotes (/batch) con backoff.
  Si el WiFi falla 3 veces seguidas, vuelve a abrir el portal. Hora por NTP: `timestamp` solo si el reloj sincronizó.

  Librerías: "WiFiManager" (tzapu), "DHT sensor library" y "Adafruit Unified Sensor" (Adafruit).
  Configuración de compilación: copiar config.h.example a config.h.
*/
#include <WiFi.h>
#include <WiFiManager.h>
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
const unsigned long PORTAL_TIMEOUT_S = 180;
const int INTENTOS_WIFI = 3;

struct Config {
  char servidor[80];
  char apiKey[72];
  char cliente[40];
  char sensor[40];
  char ubicacion[60];
  uint32_t ciclo;
};

enum : uint8_t { F_TEMP = 1, F_HUM = 2, F_GAS = 4 };

struct Muestra {
  uint32_t seq;
  time_t ts;
  float temp;
  float hum;
  uint16_t mqMv;
  uint16_t mqRaw;
  uint8_t flags;
  int8_t rssi;
};

Config cfg;
Muestra cola[COLA_MAX];
int colaIni = 0, colaN = 0;
uint32_t perdidas = 0;                   // muestras descartadas por cola llena o rechazo 4xx
uint32_t seq = 0;
Preferences prefs;
bool guardarPendiente = false;           // el formulario del portal se envió
unsigned long ultMuestra = 0, ultWiFi = 0, proximoEnvio = 0, esperaEnvio = 2000, inicio = 0;
int fallosWiFi = 0;
bool soloIndividual = false;             // tras un rechazo de lote se envía de a una para aislar la muestra mala

// ---------- Configuración persistente ----------
void cargarConfig() {
  prefs.begin("cfg", true);
  strlcpy(cfg.servidor, prefs.getString("servidor", SERVIDOR_DEFECTO).c_str(), sizeof(cfg.servidor));
  strlcpy(cfg.apiKey, prefs.getString("apikey", API_KEY_DEFECTO).c_str(), sizeof(cfg.apiKey));
  strlcpy(cfg.cliente, prefs.getString("cliente", CLIENTE_DEFECTO).c_str(), sizeof(cfg.cliente));
  strlcpy(cfg.sensor, prefs.getString("sensor", SENSOR_DEFECTO).c_str(), sizeof(cfg.sensor));
  strlcpy(cfg.ubicacion, prefs.getString("ubic", UBICACION_DEFECTO).c_str(), sizeof(cfg.ubicacion));
  cfg.ciclo = prefs.getUInt("ciclo", CICLO_S_DEFECTO);
  prefs.end();
}

bool configGuardada() {
  prefs.begin("cfg", true);
  bool ok = prefs.getBool("ok", false);
  prefs.end();
  return ok;
}

void guardarConfig() {
  prefs.begin("cfg", false);
  prefs.putString("servidor", cfg.servidor);
  prefs.putString("apikey", cfg.apiKey);
  prefs.putString("cliente", cfg.cliente);
  prefs.putString("sensor", cfg.sensor);
  prefs.putString("ubic", cfg.ubicacion);
  prefs.putUInt("ciclo", cfg.ciclo);
  prefs.putBool("ok", true);
  prefs.end();
}

void borrarConfig() {
  prefs.begin("cfg", false);
  prefs.clear();
  prefs.end();
}

// ---------- Portal cautivo ----------
WiFiManager wm;
WiFiManagerParameter pServidor("servidor", "Servidor (http://IP:8000)", "", sizeof(Config::servidor) - 1);
WiFiManagerParameter pApiKey("apikey", "API key", "", sizeof(Config::apiKey) - 1, "type=\"password\"");
WiFiManagerParameter pCliente("cliente", "ID de cliente", "", sizeof(Config::cliente) - 1);
WiFiManagerParameter pSensor("sensor", "Nombre del sensor", "", sizeof(Config::sensor) - 1);
WiFiManagerParameter pUbicacion("ubicacion", "Ubicacion", "", sizeof(Config::ubicacion) - 1);
WiFiManagerParameter pCiclo("ciclo", "Ciclo de envio (segundos, 5-3600)", "", 6, "type=\"number\" min=\"5\" max=\"3600\"");

void alGuardarParametros() {
  strlcpy(cfg.servidor, pServidor.getValue(), sizeof(cfg.servidor));
  strlcpy(cfg.apiKey, pApiKey.getValue(), sizeof(cfg.apiKey));
  strlcpy(cfg.cliente, pCliente.getValue(), sizeof(cfg.cliente));
  strlcpy(cfg.sensor, pSensor.getValue(), sizeof(cfg.sensor));
  strlcpy(cfg.ubicacion, pUbicacion.getValue(), sizeof(cfg.ubicacion));
  long c = atol(pCiclo.getValue());
  cfg.ciclo = (c >= 5 && c <= 3600) ? (uint32_t)c : CICLO_S_DEFECTO;
  guardarPendiente = true;
}

void prepararPortal() {
  pServidor.setValue(cfg.servidor, sizeof(cfg.servidor) - 1);
  pApiKey.setValue(cfg.apiKey, sizeof(cfg.apiKey) - 1);
  pCliente.setValue(cfg.cliente, sizeof(cfg.cliente) - 1);
  pSensor.setValue(cfg.sensor, sizeof(cfg.sensor) - 1);
  pUbicacion.setValue(cfg.ubicacion, sizeof(cfg.ubicacion) - 1);
  char c[8];
  snprintf(c, sizeof(c), "%lu", (unsigned long)cfg.ciclo);
  pCiclo.setValue(c, 6);
}

String nombreAP() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char n[20];
  snprintf(n, sizeof(n), "SENSOR-%02X%02X", mac[4], mac[5]);
  return String(n);
}

void abrirPortal() {
  Serial.printf("[PORTAL] red %s -> http://192.168.4.1 (%lus)\n", nombreAP().c_str(), PORTAL_TIMEOUT_S);
  prepararPortal();
  wm.setConfigPortalTimeout(PORTAL_TIMEOUT_S);
  wm.startConfigPortal(nombreAP().c_str());
  if (guardarPendiente) {
    guardarConfig();
    Serial.println("[CFG] configuración guardada en flash, reiniciando");
  }
  delay(500);
  ESP.restart();
}

void iniciarWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  wm.addParameter(&pServidor);
  wm.addParameter(&pApiKey);
  wm.addParameter(&pCliente);
  wm.addParameter(&pSensor);
  wm.addParameter(&pUbicacion);
  wm.addParameter(&pCiclo);
  wm.setSaveParamsCallback(alGuardarParametros);
  wm.setTitle("Configurar sensor");
  wm.setConnectTimeout(20);
  prepararPortal();

  if (!configGuardada()) {                 // primer encendido: portal directo
    abrirPortal();
    return;
  }
  wm.setConfigPortalTimeout(PORTAL_TIMEOUT_S);
  if (!wm.autoConnect(nombreAP().c_str())) {   // sin WiFi guardado o inalcanzable: abrió el portal y venció
    Serial.println("[WiFi] sin conexión tras el portal, reiniciando");
    delay(500);
    ESP.restart();
  }
  if (guardarPendiente) guardarConfig();
}

// ---------- WiFi ----------
void onWiFiEvent(arduino_event_id_t event, arduino_event_info_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    Serial.printf("[WiFi] desconectado, motivo %u\n", info.wifi_sta_disconnected.reason);
  } else if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    Serial.print("[WiFi] IP: ");
    Serial.println(WiFi.localIP());
  }
}

void vigilarWiFi() {
  if (WiFi.status() == WL_CONNECTED) { ultWiFi = millis(); fallosWiFi = 0; return; }
  if (millis() - ultWiFi > 30000) {        // 30 s sin conexión: reintenta; tras 3 fallos abre el portal
    fallosWiFi++;
    Serial.printf("[WiFi] sin conexión (%d/%d)\n", fallosWiFi, INTENTOS_WIFI);
    if (fallosWiFi >= INTENTOS_WIFI) abrirPortal();
    WiFi.disconnect();
    WiFi.reconnect();
    ultWiFi = millis();
  }
}

// ---------- Hora ----------
bool horaLista() { return time(nullptr) > HORA_VALIDA; }

// ---------- Sensores ----------
#if USE_MQ135 == 1
// Promedio de 16 lecturas del ADC1. analogReadMilliVolts usa la calibración de fábrica del ESP32.
void leerMQ135(uint16_t &mv, uint16_t &raw) {
  uint32_t sumMv = 0, sumRaw = 0;
  for (int i = 0; i < 16; i++) {
    sumMv += analogReadMilliVolts(MQ135_PIN);
    sumRaw += analogRead(MQ135_PIN);
    delay(2);
  }
  mv = sumMv / 16;
  raw = sumRaw / 16;
}
#endif

uint8_t leerSensores(Muestra &m) {
  uint8_t f = 0;
#if USE_DHT
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  if (!isnan(t)) { m.temp = t; f |= F_TEMP; }
  if (!isnan(h)) { m.hum = h; f |= F_HUM; }
#else
  static float st = 22.0, sh = 50.0;       // caminata aleatoria para simular un DHT
  st += random(-30, 31) / 100.0;
  sh = constrain(sh + random(-100, 101) / 100.0, 0.0, 100.0);
  m.temp = st; m.hum = sh;
  f |= F_TEMP | F_HUM;
#endif
#if USE_MQ135 == 1
  if (millis() - inicio >= MQ135_PRECALENTAMIENTO_MS) {   // el calentador necesita unos minutos para estabilizar
    leerMQ135(m.mqMv, m.mqRaw);
    f |= F_GAS;
  }
#elif USE_MQ135 == 2
  static float sg = 900.0;
  sg = constrain(sg + random(-25, 26), 300.0, 2500.0);
  m.mqMv = (uint16_t)sg;
  m.mqRaw = (uint16_t)(sg * 4095.0 / 3300.0);
  f |= F_GAS;
#endif
  return f;
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
  out += "{\"sensor\":\"";   out += cfg.sensor;
  out += "\",\"cliente\":\""; out += cfg.cliente;
  out += "\",\"ubicacion\":\""; out += cfg.ubicacion;
  out += "\",\"seq\":"; out += (unsigned long)m.seq;
  if (m.ts > HORA_VALIDA) {
    struct tm tmv;
    gmtime_r(&m.ts, &tmv);
    char f[24];
    strftime(f, sizeof(f), "%Y-%m-%dT%H:%M:%SZ", &tmv);
    out += ",\"timestamp\":\""; out += f; out += "\"";
  }
  out += ",\"rssi\":"; out += (int)m.rssi;
  out += ",\"fw_version\":\"" FW_VERSION "\",\"mediciones\":[";
  char b[96];
  bool primero = true;
  auto agrega = [&](const char *tipo, float v, const char *u, int dec) {
    snprintf(b, sizeof(b), "%s{\"tipo\":\"%s\",\"valor\":%.*f,\"unidad\":\"%s\"}", primero ? "" : ",", tipo, dec, v, u);
    out += b;
    primero = false;
  };
  if (m.flags & F_TEMP) agrega("temperatura", m.temp, "C", 1);
  if (m.flags & F_HUM) agrega("humedad", m.hum, "%", 1);
  if (m.flags & F_GAS) {
    agrega("calidad_aire_mv", m.mqMv, "mV", 0);
    agrega("calidad_aire_raw", m.mqRaw, "adc", 0);
  }
  out += "]}";
}

int postJson(const char *path, const String &body) {
  HTTPClient http;
  String url = String(cfg.servidor);
  if (url.endsWith("/")) url.remove(url.length() - 1);
  url += path;
#if USE_HTTPS
  WiFiClientSecure client;
  client.setInsecure();                  // SOLO pruebas: no valida el certificado
  http.begin(client, url);
#else
  WiFiClient client;
  http.begin(client, url);
#endif
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", cfg.apiKey);
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
  } else {                               // 401/403/404 (clave o cliente mal configurados), 5xx, timeout: conservar y reintentar
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
  inicio = millis();
  Serial.printf("\n=== ESP32 -> API de sensores · fw %s ===\n", FW_VERSION);

  pinMode(PIN_RESET_CONFIG, INPUT_PULLUP);
  if (digitalRead(PIN_RESET_CONFIG) == LOW) {            // BOOT mantenido 3 s: borra WiFi y configuración
    unsigned long t0 = millis();
    while (digitalRead(PIN_RESET_CONFIG) == LOW && millis() - t0 < 3000) delay(50);
    if (digitalRead(PIN_RESET_CONFIG) == LOW) {
      Serial.println("[CFG] BOOT mantenido: se borran WiFi y configuración");
      borrarConfig();
      wm.resetSettings();
    }
  }

  cargarConfig();
  prefs.begin("envio", false);
  seq = prefs.getUInt("seq", 0) + SEQ_MARGEN;            // salta un margen: tras un reinicio no se reutilizan seq
  prefs.putUInt("seq", seq);
  Serial.printf("[SEQ] inicio en %lu\n", (unsigned long)seq);

#if USE_DHT
  dht.begin();
#endif
#if USE_MQ135 == 1
  analogReadResolution(12);
  analogSetPinAttenuation(MQ135_PIN, ADC_11db);          // rango ~0-3,3 V
#endif
  WiFi.onEvent(onWiFiEvent);
  iniciarWiFi();
  Serial.printf("[CFG] sensor=%s cliente=%s ciclo=%lus servidor=%s\n", cfg.sensor, cfg.cliente,
                (unsigned long)cfg.ciclo, cfg.servidor);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  ultWiFi = millis();
}

void loop() {
  vigilarWiFi();

  if (millis() - ultMuestra >= cfg.ciclo * 1000UL) {
    ultMuestra = millis();
    Muestra m = {};
    m.flags = leerSensores(m);
    if (m.flags) {
      m.seq = seq++;
      m.ts = horaLista() ? time(nullptr) : 0;
      m.rssi = (int8_t)WiFi.RSSI();
      if (seq % SEQ_MARGEN == 0) { prefs.putUInt("seq", seq); }
      encolar(m);
      Serial.printf("[MUESTRA] seq=%lu T=%.1f H=%.1f gas=%umV flags=%u cola=%d perdidas=%lu hora=%s\n",
                    (unsigned long)m.seq, m.temp, m.hum, m.mqMv, m.flags, colaN, (unsigned long)perdidas,
                    m.ts ? "NTP" : "sin NTP");
    } else {
      Serial.println("[SENSOR] ninguna lectura válida, muestra omitida");
    }
  }

  vaciarCola();
  delay(10);
}
